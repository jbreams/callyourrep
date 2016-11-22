from flask import Flask, request, json
from flask.ext.pymongo import PyMongo
from twilio.util import TwilioCapability
from twilio import twiml
from datetime import datetime
import phonenumbers
from bson import json_util

app = Flask(__name__)
app.config['MONGO_DBNAME'] = 'callyourrep'
mongo = PyMongo(app)

@app.route('/api/districts.json', methods=['GET'])
def getDistricts():
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    query = { 'district': { '$geoIntersects': { '$geometry': {
        'type': 'Point', 'coordinates': [ float(lon), float(lat) ]}}}}

    districts = [ d for d in mongo.db.districts.find(query) ]
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
    districtId = str(request.args.get('district'))
    query = { '$or': [ {'district': districtId }, {'district': { '$exists': False }}],
        '$or': [ { 'expires': { '$exists': False } }, { 'expires': {'$lt': datetime.now()}} ] }
    topics = mongo.db.topics.find(query, {'$_id': 0 })
    return ")]}',\n" + json_util.dumps([ t for t in topics ])

@app.route('/api/inbound')
def inbound():
    resp = twiml.Response()
    phoneNumber = request.args.get('PhoneNumber')
    addressHash = request.args.get('AddressHash')
    district = mongo.db.districts.find_one({'phone': phoneNumber})

    with resp.dial(callerId=app.config['TWILIO_OUTGOING_NUMBER']) as dial:
        if district:
            mongo.db.districts.update_one({'_id': district['_id']}, { '$inc': { 'calls': 1 }})
            parsed = phonenumbers.parse(phoneNumber, 'US')
            dial.timeLimit(900)
            dial.number(phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164))

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
