from bson import json_util
from bson.objectid import ObjectId
from callyourrep import app, mongo, utc, users, twilioClient
from datetime import datetime, timedelta
from flask import Flask, request, json, render_template, session, redirect, url_for
from flask.ext.pymongo import PyMongo, ASCENDING, DESCENDING
from twilio import twiml
from twilio.rest import TwilioRestClient
from twilio.util import TwilioCapability
import jsonschema
import phonenumbers
import stripe

from pprint import pprint

def generateFailureMessage():
    resp = twiml.Response()
    resp.say("I could not find the number you wanted to call.")
    resp.say("Please visit call your rep dot U.S. to make a call.")
    resp.say("Or, text your address to {0} to try again".format(
        app.config['TWILIO_OUTGOING_NUMBER']))
    return str(resp)

@app.route('/api/voiceInbound', methods=['POST'])
def voiceInbound():
    callSid = request.form['CallSid']
    targetPhoneNumber = request.form['To']
    callStatus = request.form['CallStatus']
    sourcePhoneNumber = request.form['From']
    callDuration = request.form.get('CallDuration', None)

    targetContact = request.form.get('CYRContact', None)
    targetLocation = request.form.get('CYRLocation', None)
    targetCallScript = request.form.get('CYRCallScript', None)

    targetCallScript = None if targetCallScript == "null" else targetCallScript

    if callStatus != 'ringing':
        mongo.db.calls.update_one(
            {'_id': callSid},
            {'$set': {
                'callDuration': callDuration,
                'lastCallStatus': callStatus,
                'lastTimestamp': datetime.now(utc)
            }}
        )
        resp = twiml.Response()
        return str(resp)

    connectTo = None
    outboundNumber = None

    if not targetPhoneNumber and not targetContact:
        return generateFailureMessage()

    if targetContact:
        try:
            targetContact = ObjectId(targetContact)
            if targetCallScript:

                targetCallScript = ObjectId(targetCallScript)
        except:
            resp = twiml.Response()
            resp.say("Hard core failure!")
            return str(resp)

        contact = mongo.db.contacts.find_one({'_id': ObjectId(targetContact)})
        if not contact:
            return generateFailureMessage()
        connectTo = contact['phoneNumber']
        outboundNumber = app.config['TWILIO_OUTGOING_NUMBER']

    elif targetPhoneNumber:
        callScript = mongo.db.callscripts.find_one({'phoneNumber': targetPhoneNumber})
        if not callScript:
            return generateFailureMessage()
        contactId = [ v for v in callScript['appliesTo'] if isinstance(v, ObjectId) ]
        if len(contactId) == 0:
            return generateFailureMessage()
        contact = mongo.db.contacts.find_one({'_id': contactId[0]})
        if not contact:
            return generateFailureMessage()
        connectTo = contact['phoneNumber']
        targetCallScript = callScript['_id']
        targetContact = contact['_id']
        outboundNumber = targetPhoneNumber

    mongo.db.calls.insert_one({
        '_id': callSid,
        'lastCallStatus': callStatus,
        'callDuration': callDuration,
        'targetContact': targetContact,
        'targetCallScript': targetCallScript,
        'targetLocation': targetLocation,
        'createdAt': datetime.now(utc),
        'lastTimestamp': datetime.now(utc),
        'connectedTo': connectTo
    })

    mongo.db.contacts.update_one(
        {'_id': targetContact},
        {'$inc': { 'calls': 1 }}
    )

    if targetCallScript:
        mongo.db.callscripts.update_one(
            {'_id': targetCallScript},
            {'$inc': { 'calls': 1 }}
        )

    resp = twiml.Response()
    resp.dial(number=connectTo, callerId=outboundNumber, timeLimit=1200)
    return str(resp)

