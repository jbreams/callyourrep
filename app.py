from flask import Flask, request, json, render_template, session
from flask.ext.pymongo import PyMongo, ASCENDING, DESCENDING
from twilio.util import TwilioCapability
from twilio import twiml
from twilio.rest import TwilioRestClient
from datetime import datetime, timedelta
import phonenumbers
import requests
from bson import json_util
from bson.objectid import ObjectId
import pytz
import os

from pprint import pprint

app = Flask(__name__)
for (k, v) in os.environ.items():
    if k.startswith(('MONGODB_', 'TWILIO_', 'GOOGLE_')):
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

utc = pytz.utc

@app.route('/api/districts.json', methods=['GET'])
def getDistricts():
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    query = { 'district': { '$geoIntersects': { '$geometry': {
        'type': 'Point', 'coordinates': [ float(lon), float(lat) ]}}}}

    districts = [ d for d in mongo.db.districts.find(query).sort('_id', ASCENDING) ]
    for (idx, d) in enumerate(districts):
        betterCommittees = []
        for c in d['committees']:
            betterData = mongo.db.committees.find_one({'_id': c['committee']})
            betterData['rank'] = c['rank']
            betterCommittees.append(betterData)
        districts[idx]['committees'] = betterCommittees

    updateQuery = { '_id': { '$in': [ d['_id'] for d in districts ] }}
    mongo.db.districts.update_many(updateQuery, { '$inc': { 'searches': 1 }})

    return json.dumps(districts)

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

@app.route('/api/inbound')
def inbound():
    resp = twiml.Response()
    phoneNumber = request.args.get('PhoneNumber')
    addressHash = request.args.get('AddressHash')
    callStatus = request.args.get('CallStatus')

    district = mongo.db.districts.find_one({'phone': phoneNumber})
    if not district:
        resp.say("You are trying to call an unknown phone number")
        return str(resp)

    parsedNumber = phonenumbers.format_number(phonenumbers.parse(district['phone'], 'US'),
        phonenumbers.PhoneNumberFormat.E164)

    lastCall = mongo.db.calls.find_one({'addressHash': addressHash,
                                        'phoneNumber': parsedNumber})
    now = datetime.now(utc)
    if lastCall and lastCall['timestamp'] + timedelta(hours=24) > now:
        resp.say("You have already called " + phoneNumber + " in the last 24 hours." +
                 "Please try again tomorrow")
        return str(resp)

    resp.dial(number=parsedNumber,
            callerId=app.config['TWILIO_OUTGOING_NUMBER'],
            timeLimit=1200)
    mongo.db.districts.update_one({'_id': district['_id']}, { '$inc': { 'calls': 1 }})
    mongo.db.calls.insert_one({'timestamp': now,
                               'addressHash': addressHash,
                               'phoneNumber': parsedNumber})

    return str(resp)

@app.route('/api/smsCallResponse', methods=['POST', 'GET'])
def smsCallResponse():
    resp = twiml.Response()
    callId = request.args.get("callId", None)
    if not callId:
        resp.say("Sorry, I couldn't find the call you wanted.")
        resp.say("Text your address to {0} to try again".format(
            app.config['TWILIO_OUTGOING_NUMBER']))
        return str(resp)

    callInfo = mongo.db.calls.find_one({'_id': ObjectId(callId)})

    if not callInfo:
        resp.say("Sorry, I couldn't find the call you wanted.")
        resp.say("Text your address to {0} to try again".format(
            app.config['TWILIO_OUTGOING_NUMBER']))
        return str(resp)

    rep = callInfo['districts'][callInfo['nextDistrict']]

    resp.say("I'm connecting you to {}, the {}".format(rep['repName'], rep['fullTitle']))
    resp.dial(number=rep['phone'],
            callerId=app.config['TWILIO_OUTGOING_NUMBER'],
            timeLimit=1200)

    return str(resp)

@app.route('/api/smsInbound', methods=['POST', 'GET'])
def smsInbound():
    callId = ObjectId(session.get("callId", ObjectId()))
    callInfo = mongo.db.calls.find_one({'_id': callId})

    if not callInfo:
        callInfo = { '_id': callId }
        params = {
            'key': app.config['GOOGLE_API_KEY'],
            'query': request.args.get("Body"),
        }
        r = requests.get("https://maps.googleapis.com/maps/api/place/textsearch/json", params=params)
        addressResult = r.json()['results'][0]['geometry']['location']
        query = { 'district': { '$geoIntersects': { '$geometry': {
            'type': 'Point', 'coordinates': [
                float(addressResult['lng']), float(addressResult['lat']) ] } } } }

        districts = []
        for d in mongo.db.districts.find(query).sort('_id', ASCENDING):
            parsedNumber = phonenumbers.format_number(phonenumbers.parse(d['phone'], 'US'),
                phonenumbers.PhoneNumberFormat.E164)
            districts.append({
                '_id': d['_id'],
                'phone': parsedNumber,
                'repName': d['repName'],
                'fullTitle': d['fullTitle'],
            })
        if len(districts) == 0:
            twilioResp.message(
                "Sorry, I couldn't find your congressional representatives! I'll look into it!")
            return str(twilioResp)

        callInfo['districts'] = districts
        callInfo['nextDistrict'] = 0
        callInfo['address'] = addressResult
        callInfo['callBack'] = request.args.get("From")

        mongo.db.calls.insert_one(callInfo)

    else:
        callInfo['nextDistrict'] += 1
        if callInfo['nextDistrict'] > len(callInfo['districts']):
            callInfo['nextDistrict'] = 0
        mongo.db.calls.replace_one({'_id': callInfo['_id']}, callInfo)

    call = twilioClient.calls.create(
        url=app.config['BASE_URL'] + '/api/smsCallResponse' + '?callId=' + str(callInfo['_id']),
        to=callInfo['callBack'],
        from_=app.config['TWILIO_OUTGOING_NUMBER'])

    session['callId'] = str(callInfo['_id'])
    resp = twiml.Response()
    resp.message("Okay, I'll connect you. Text 'again' after your call to call your next rep!")
    return str(resp)

@app.route('/api/twilioToken')
def token():
    capability = TwilioCapability(
            app.config['TWILIO_ACCOUNT_SID'], app.config['TWILIO_AUTH_TOKEN'])
    capability.allow_client_outgoing(app.config['TWILIO_APP_SID'])
    ret = capability.generate()
    return ret

@app.route('/')
def index2():
    return render_template('index.html',
        googleAPIKey=app.config['GOOGLE_API_KEY'],
        googleAnalyticsKey=app.config['GOOGLE_ANALYTICS_KEY'])

@app.route('/caller')
def caller():
    search = request.args.get("topicId");
    topics = None

    if search:
        topics = json_util.dumps(mongo.db.topics.find_one_and_update(
            {'_id': ObjectId(search)},
            {'$inc': { 'searchCount': 1 }}
        ))
    else:
        topics = "null"

    return render_template('caller.html',
        googleAPIKey=app.config['GOOGLE_API_KEY'],
        googleAnalyticsKey=app.config['GOOGLE_ANALYTICS_KEY'],
        topicDict=topics)

if __name__ == '__main__':
    app.run()
