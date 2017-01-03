from bson import json_util
from bson.objectid import ObjectId
from datetime import datetime, timedelta
from flask import Flask, request, json, render_template, session, redirect, url_for
from flask.ext.pymongo import PyMongo, ASCENDING, DESCENDING
from twilio import twiml
from twilio.rest import TwilioRestClient
from twilio.util import TwilioCapability
import os
import phonenumbers
import pytz
import requests
import stripe

from pprint import pprint

app = Flask(__name__)
for (k, v) in os.environ.items():
    if k.startswith(('MONGODB_', 'TWILIO_', 'GOOGLE_', 'STRIPE_')):
        app.config[k] = v
    elif k in [ 'SESSION_SECRET_KEY', 'BASE_URL' ]:
        app.config[k] = v

from flask_sslify import SSLify
if 'DYNO' in os.environ: # only trigger SSLify if the app is running on Heroku
    sslify = SSLify(app)

app.config.from_envvar('CALLYOURREP_SETTINGS', silent=True)
app.secret_key = app.config['SESSION_SECRET_KEY']
mongo = PyMongo(app, 'MONGODB')

jinja_options = app.jinja_options.copy()

jinja_options.update(dict(
    block_start_string='<%',
    block_end_string='%>',
    variable_start_string='%%',
    variable_end_string='%%',
    comment_start_string='<#',
    comment_end_string='#>'
))
app.jinja_options = jinja_options

twilioClient = TwilioRestClient(app.config['TWILIO_ACCOUNT_SID'], app.config['TWILIO_AUTH_TOKEN'])
stripe.api_key = app.config['STRIPE_SECRET_KEY']

utc = pytz.utc

import callyourrep.users as users
import callyourrep.callscripts as callscripts
import callyourrep.campaigns as campaigns
import callyourrep.contacts as contacts
import callyourrep.calls as calls

@app.route('/api/topics.json', methods=['GET'])
def getTopics():
    search = request.args.get("search")
    if not search:
        topics = mongo.db.topics.find().sort('searchCount', DESCENDING).limit(4)
    else:
        terms = { '$text': {
            '$search': str(search), '$language': 'en', '$caseSensitive': False}}
        topics = mongo.db.topics.find(terms).sort(
                'searchCount', DESCENDING)
    return json_util.dumps([ t for t in topics ])

@app.route('/api/twilioToken')
def token():
    capability = TwilioCapability(
            app.config['TWILIO_ACCOUNT_SID'], app.config['TWILIO_AUTH_TOKEN'])
    capability.allow_client_outgoing(app.config['TWILIO_APP_SID'])
    ret = capability.generate()
    return ret

@app.route('/')
@users.loginOptional
def index2():
    return render_template('index.html',
        googleAPIKey=app.config['GOOGLE_API_KEY'],
        googleAnalyticsKey=app.config['GOOGLE_ANALYTICS_KEY'])

@app.route('/manage')
@users.loginRequired
def manage():
    campaignId = request.args.get("campaign", None, str)
    campaignsList = campaigns.getCampaigns(None)
    if not campaignId:
        (firstPublic, firstPrivate) = (None, None)
        for (i, v) in campaignsList.items():
            if v['type'] == 'private' and not firstPrivate:
                firstPrivate = i
            else:
                firstPublic = i
        campaignId = firstPrivate if firstPrivate else firstPublic
    user = users.getUser(None, request.userId)

    return render_template('manage.html',
        googleAPIKey=app.config['GOOGLE_API_KEY'],
        googleAnalyticsKey=app.config['GOOGLE_ANALYTICS_KEY'],
        callScripts=json.dumps(callscripts.getCallScripts(None, campaignId, None)),
        campaignId=json.dumps(campaignId),
        campaigns=json.dumps(campaignsList),
        loggedInUser=json.dumps(user),
    )

@app.route('/manageCampaign')
@users.loginRequired
def manageCampaign():
    campaignId = request.args.get("campaign", None, ObjectId)
    campaign = None
    if campaignId:
        campaign = campaigns.getCampaigns(campaignId)
        print campaign
        if campaign and str(campaignId) not in campaign:
            campaign = None
        else:
            campaign = campaign[str(campaignId)]
    usersList = [ users.getUser(None, request.userId) ]
    if campaign and 'owners' in campaign:
        for o in campaign['owners']:
            usersList.append(users.getUser(None, o))
    if campaign and 'billingOwner' in campaign:
        if campaign['billingOwner']:
            usersList.append(users.getUser(None, campaign['billingOwner']))

    return render_template('managecampaign.html',
        googleAPIKey=app.config['GOOGLE_API_KEY'],
        googleAnalyticsKey=app.config['GOOGLE_ANALYTICS_KEY'],
        stripePublishableKey=app.config['STRIPE_PUBLISHABLE_KEY'],
        campaign=json.dumps(campaign),
        users=json.dumps(dict([(u['_id'], u) for u in usersList])),
        loggedInUser=json.dumps(str(request.userId)),
    )

@app.route('/caller')
@users.loginOptional
def caller():
    topicId = request.args.get("topicId", None);
    topicData = None
    if topicId:
        try:
            print topicId
            topicData = callscripts.getCallScripts(ObjectId(topicId), None, None)
            print topicData
            if topicData and topicId in topicData:
                topicData = topicData[topicId]
        except Exception as e:
            print e
            pass
    if not topicData:
        topicData = "null"
    else:
        topicData = json.dumps(topicData)

    return render_template('caller.html',
        googleAPIKey=app.config['GOOGLE_API_KEY'],
        googleAnalyticsKey=app.config['GOOGLE_ANALYTICS_KEY'],
        topicData=topicData)

if __name__ == '__main__':
    app.run()
