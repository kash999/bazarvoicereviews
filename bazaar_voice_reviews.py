import urllib2
import simplejson
import math
import dateutil.parser
import httplib
import socket
import sys
import time
from django.conf import settings
# from django.core.cache import cache  # uncommint this line using with in django project
from django.utils.http import urlencode


"""
   Bazar voice is thied party reviewing site.
   Aim of this code is wrapper around their api for easy getting reviews, paging
   and updating most helpful  with cacheing

"""

# soon updating code to use requsts wrapper around urllib3


def urlopen(url, data=None, timeout=None):
    """
    urlopen() with timeout, for Python 2.5

    url, data - Passed to urllib2.urlopen, see urllib2 docs.
    timeout   - Socket timeout in seconds, used when opening the
                connection and receiving data. Currently only
                implemented for HTTP connections.
    """

    class HTTPHandlerWithTimeout(urllib2.HTTPHandler):

        def do_open(self, http_class, req):
            http_class = HTTPConnectionWithTimeout
            return urllib2.HTTPHandler.do_open(self, http_class, req)

    class HTTPConnectionWithTimeout(httplib.HTTPConnection):

        def __setattr__(self, name, value):
            if name == 'sock' and value is not None and timeout is not None:
                value.settimeout(timeout)
            httplib.HTTPConnection.__dict__[name] = value

    if timeout is None:
        timeout = socket.getdefaulttimeout()

    opener = urllib2.build_opener(HTTPHandlerWithTimeout)
    response = opener.open(url, data)

    return response


def persistent_urlopen(url, data=None, timeout=None, attempts=5,
                       first_delay=2.0, delay_multiplier=2.0, debug=False):
    """
    A urlopen() that retries fetching the URL in case of error.

    url, data, timeout - See urlopen() above.
    attempts           - Max. number of attempts before aborting.
    first_delay        - If the first urlopen fails, wait this amount of time in
                         seconds before retrying. Subsequent delays will be
                         multiplied by delay_multiplier.
    delay_multiplier   - See first_delay.
    """

    class URLError(urllib2.URLError):
        pass

    attempt = 1
    delay = first_delay
    while True:
        try:
            return urlopen(url, data, timeout)
        except (IOError, httplib.HTTPException,) as e:
            message = (
                '%(class)s: %(exception)s (attempt:%(attempt)d) (url:%(url)s)'
            ) % {
                'class': '%s.%s' % (e.__class__.__module__, e.__class__.__name__,),
                'exception': e,
                'attempt': attempt,
                'url': url,
            }

            attempt += 1
            if attempt > attempts:
                # Re-raise as a URLError for debugging. Retains stack trace.
                raise URLError, URLError(message), sys.exc_info()[2]
            else:
                if debug:
                    print >>sys.stderr, message
                    print >>sys.stderr, 'Retrying in %f seconds' % delay
                time.sleep(delay)
                delay *= delay_multiplier


class BazarVoiceReviews(object):

    def __init__(self, product):

        self.host = settings.BAZAAR_VOICE_URL + '/data/'
        self.product = product
        self.prod_id = self._get_prod_id(product)

    def _make_url(self, jtype):

        url = self.host + jtype + '.json?apiversion=' + settings.BAZAAR_VOICE_API_VERSION
        url += '&passkey=' + settings.BAZAAR_VOICE_API_KEY
        url += '&Filter=ProductId:' + self.prod_id
        return url

    def get_stats(self):

        url = self._make_url('statistics')
        url += '&stats=NativeReviews'

        try:
            r = persistent_urlopen(url, timeout=10, attempts=3).read()
        except (urllib2.URLError, urllib2.HTTPError):
            r = None

        if r:
            data = simplejson.loads(r)
            return data.get('Results')[0].get('ProductStatistics').get('NativeReviewStatistics')
        else:
            data = {}
            return data

    def get_details_stats(self):
        url = self._make_url('reviews')
        url += '&Include=Products&Stats=Reviews'

        overall_rating_range = 0
        total_review_count = 0
        average_overall_rating = 0
        rating_distribution = 0

        data = []
        if cache.get(url):
            data = cache.get(url)
        else:
            try:
                r = persistent_urlopen(url, timeout=10, attempts=3).read()
            except (urllib2.URLError, urllib2.HTTPError):
                r = None

            if r:
                try:
                    data = simplejson.loads(r)
                    cache.add(url, data, 300)
                except ValueError:
                    data = []
        try:
            if data:
                rd = data['Includes']['Products'][self.prod_id]
                overall_rating_range = rd['ReviewStatistics'].get('OverallRatingRange')
                total_review_count = rd.get('TotalReviewCount')
                average_overall_rating = round(rd['ReviewStatistics'].get('AverageOverallRating'), 1)
                rating_distribution = rd['ReviewStatistics'].get('RatingDistribution')

            d = {
                'OverallRatingRange': overall_rating_range,
                'TotalReviewCount': total_review_count,
                'AverageOverallRating': average_overall_rating,
                'RatingDistribution': rating_distribution
            }

            d['product'] = self.product

            return d
        except KeyError:
            return ''

    def get_reviews(self, cookies=None, page=1, limit=8, sort='newest'):

        page = int(page) if page and str(page).isdigit() else 1
        limit = int(limit) if limit and str(limit).isdigit() else 8

        url = self._make_url('reviews')
        url += '&Include=Products&Stats=Reviews'
        url += '&Sort=' + self._sort_option(sort)
        url += '&Offset=' + self._offset(page, limit)
        url += '&Limit=' + str(limit)
        data = None
        if cache.get(url):
            data = cache.get(url)
        else:
            try:
                r = persistent_urlopen(url, timeout=10, attempts=3).read()
            except (urllib2.URLError, urllib2.HTTPError):
                r = None

            if r:
                try:
                    data = simplejson.loads(r)
                    cache.add(url, data, 300)
                except ValueError:
                    data = None
        try:
            if data and data.get('Includes', None) and data.get('Includes', None).get('Products', None):
                rd = data.get('Includes').get('Products').get(self.prod_id)
                data.update({
                    'OverallRatingRange': rd.get('ReviewStatistics').get('OverallRatingRange'),
                    'TotalReviewCount': rd.get('TotalReviewCount'),
                    'AverageOverallRating': round(rd.get('ReviewStatistics').get('AverageOverallRating'), 1),
                    'RatingDistribution': rd.get('ReviewStatistics').get('RatingDistribution')
                })

                p = Pagination(page, limit, data.get('TotalResults'))
                data['number_of_pages'] = p.iter_pages()
                data['url'] = url
                data['sorted'] = sort
                data['review_pages'] = p.pages

                data['page_num'] = page
                data['next_page'] = p.has_next
                data['back_page'] = p.has_prev
                data['product'] = self.product
                rids = self._decode_cookies(cookies) if cookies else []

                for r in data.get('Results'):
                    r['SubmissionTime'] = dateutil.parser.parse(r.get('SubmissionTime'))
                    if r.get('Id') + '_P' in rids:
                        r['disable_helpful'] = True
                        r['vote'] = 'P'
                    if r.get('Id') + '_N' in rids:
                        r['disable_helpful'] = True
                        r['vote'] = 'N'
                return data
            else:
                return ''
        except KeyError:
            return ''

    def _offset(self, page=1, limit=8):

        if int(page) == 1:
            return str(0)

        return str((page * limit) - limit)

    def _sort_option(self, sort):

        option = {'newest': 'SubmissionTime:desc',
                  'oldest': 'SubmissionTime:asc',
                  'highrating': 'Rating:desc,SubmissionTime:desc',
                  'lowrating': 'Rating:asc,SubmissionTime:desc',
                  'helpful': 'Helpfulness:desc,SubmissionTime:desc'}

        return option.get(sort, 'SubmissionTime:desc')

    def _decode_cookies(self, rids):

        if rids:
            try:
                return str(rids).decode('hex_codec').decode('zlib_codec').split(',')
            except:
                pass
        return []

    def post_most_helpful(self, rid, vote='Positive'):
        '''http://[yourHostname]/data/submitfeedback.[FORMAT]?
            ApiVersion=[latestApiVersion]
            &PassKey=[yourKey]
            &ContentType=review
            &ContentId=[ContentId]
            &UserId=[UserId]
            &FeedbackType=helpfulness
            &Vote=(Positive|Negative)'''
        if not rid:
            return ''

        con_id, sub_id = rid

        params = {
            'ApiVersion': settings.BAZAAR_VOICE_API_VERSION,
            'passkey': settings.BAZAAR_VOICE_API_KEY,
            'ContentType': 'review',
            'ContentId': con_id,
            'SubmissionId': sub_id,
            'FeedbackType': 'helpfulness',
            'vote': vote,
            'Action': 'submit',
        }
        method = '/data/submitfeedback.json'
        p = urlencode(params)

        try:
            r = persistent_urlopen(settings.BAZAAR_VOICE_URL + method, data=p, timeout=10, attempts=3).read()
        except (urllib2.URLError, urllib2.HTTPError):
            r = None

        if r:
            data = simplejson.loads(r)
        else:
            data = ''

        return data

    def _get_prod_id(self, product):
        prod_dict = {'car': 'APV_MMV_284', 'home': 'HP_MHO_322'}
        return prod_dict.get(product)


class Pagination(object):

    def __init__(self, page, per_page, total_count):

        self.page = page
        self.per_page = per_page
        self.total_count = int(total_count)

    @property
    def pages(self):
        return int(math.ceil(self.total_count / float(self.per_page)))

    @property
    def has_prev(self):
        return self.page - 1 if self.page > 1 else False

    @property
    def has_next(self):
        return self.page + 1 if self.page < self.pages else False

    def iter_pages(self, left_edge=1, left_current=2,
                   right_current=3, right_edge=1):
        last = 0
        l = []
        for num in xrange(1, self.pages + 1):
            if num <= left_edge or \
                (num > self.page - left_current - 1 and
                 num < self.page + right_current) or \
                    num > self.pages - right_edge:
                if last + 1 != num:
                    l.append('..')
                l.append(num)
                last = num
        return l


if __name__ == '__main__':

    settings.configure()
    from django.core.cache import cache

    settings.BAZAAR_VOICE_API_VERSION = '5.3'

    settings.BAZAAR_VOICE_URL = '<you personal link>'
    # Override per environment

    settings.BAZAAR_VOICE_API_KEY = '<api key provided by bv>'

    bv = BazarVoiceReviews('product name')

    print bv.get_reviews()
