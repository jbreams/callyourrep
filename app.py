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

    districts = mongo.db.districts.find(query)
    return ")]}',\n" + json.dumps([ d for d in districts ])

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
    with resp.dial(callerId=app.config['TWILIO_OUTGOING_NUMBER']) as dial:
        phoneNumber = request.args.get('PhoneNumber')
        district = mongo.db.districts.find_one({'phone': phoneNumber})
        if district:
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
