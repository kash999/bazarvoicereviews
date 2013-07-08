from django.shortcuts import render_to_response, redirect
from django.template import RequestContext
from lib.apps.bazaar_voice.bazaar_voice_reviews import BazarVoiceReviews
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse
import simplejson as json


def index(request, product, page=1):

    bv = BazarVoiceReviews(product)
    sort = request.session.get('review_sort_by') if request.session.get('review_sort_by') else 'newest'
    if request.method == 'POST':
        post = request.POST
        sort = post.get('review_sort')
        request.session['review_sort_by'] = sort

        return redirect('/customer-reviews/' + product)

    if request.GET.get('dataonly') or request.GET.get('json'):
        limit = request.GET.get('limit', 5)
        page = request.GET.get('page', 1)
        sort = request.GET.get(sort, 'newest')
        sort = sort if sort in ['lowrating', 'highrating', 'oldest', 'newest', 'helpful'] else 'newest'
        data = bv.get_reviews(page=page, sort=sort, limit=limit)
        return HttpResponse(json.dumps({'d': data}, cls=DjangoJSONEncoder), mimetype='application/json')

    data = bv.get_reviews(page=page, sort=sort)
    return render_to_response('customer-reviews/index.html', data, context_instance=RequestContext(request))
