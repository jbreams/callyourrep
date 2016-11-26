from flask import Flask, request, json
from flask.ext.pymongo import PyMongo, ASCENDING, DESCENDING
from twilio.util import TwilioCapability
from twilio import twiml
from datetime import datetime, timedelta
import phonenumbers
from bson import json_util
import pytz

app = Flask(__name__)
app.config.from_envvar('CALLYOURREP_SETTINGS', silent=True)
app.config['MONGO_DBNAME'] = 'callyourrep'
mongo = PyMongo(app)

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

    return ")]}',\n" + json.dumps(districts)

@app.route('/api/topics.json', methods=['GET'])
def getTopics():
    search = str(request.args.get("search"))
    topics = mongo.db.topics.find({ '$text': {
        '$search': search, '$language': 'en', '$caseSensitive': False}})
    return ")]}',\n" + json_util.dumps([ t for t in topics ])

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
            timeLimit=900)
    mongo.db.districts.update_one({'_id': district['_id']}, { '$inc': { 'calls': 1 }})
    mongo.db.calls.insert_one({'timestamp': now,
                               'addressHash': addressHash,
                               'phoneNumber': parsedNumber})

    return str(resp)

@app.route('/api/twilioToken')
def token():
    capability = TwilioCapability(
            app.config['TWILIO_ACCOUNT_SID'], app.config['TWILIO_AUTH_TOKEN'])
    capability.allow_client_outgoing(app.config['TWILIO_APP_SID'])
    ret = capability.generate()
    return ret


if __name__ == '__main__':
    app.run()
