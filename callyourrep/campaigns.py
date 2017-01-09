from bson import json_util
from bson.objectid import ObjectId
from callyourrep import app, mongo, utc, users, twilioClient
from datetime import datetime, timedelta
from flask import Flask, request, json, render_template, session, redirect, url_for
from flask.ext.pymongo import PyMongo, ASCENDING, DESCENDING
import jsonschema
import phonenumbers
import stripe

campaignSchema = {
    '$schema': 'https://www.callyourrep.us/schemas/campaignSchema.json',
    'type': 'object',
    'properties': {
        '_id': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'name': { 'type': 'string' },
        'type': { 'type': 'string', 'enum': [ 'public', 'private' ] },
        'owners': {
            'type': 'array',
            'items': {
                'type': 'string',
                'pattern': '^[A-Fa-f\d]{24}$',
            }
        },
        'billingOwner': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'expiresOn': { 'type': 'string', 'format': 'date-time' },
    },
    'required': [
        'name',
        'type',
        'owners',
        'billingOwner',
    ]
}
@app.route('/schemas/campaignSchema.json')
def getCampaignSchema():
    return json.dumps(campaignSchema)

@app.route('/api/campaigns', methods=['PUT'])
@users.loginRequired
def putCampaignApi():
    try:
        return json.dumps({'status': 'OK', 'result': putCampaign(request.get_json())})
    except Exception as e:
        return json.dumps({'status': 'FAIL', 'error_message': str(e) })

def putCampaign(newCampaign):
    jsonschema.validate(newCampaign, campaignSchema)
    newCampaignId = ObjectId()
    if '_id' in newCampaign:
        newCampaign['_id'] = ObjectId(newCampaign['_id'])
        newCampaignId = newCampaign['_id']
    else:
        newCampaign['_id'] = newCampaignId

    if 'phoneNumbers' in newCampaign:
        del newCampaign['phoneNumbers']

    serviceAccounts = [ acct['_id'] for acct in mongo.db.users.find(
        {'campaign': newCampaignId, 'type': 'service' }
    )]
    newCampaign['owners'] += serviceAccounts
    seen = set()
    newCampaign['owners'] = [o for o in newCampaign['owners'] if o not in seen and not seen.add(o)]

    for (i, v) in enumerate(newCampaign['owners']):
        newCampaign['owners'][i] = ObjectId(v)

    oldCampaignDoc = mongo.db.campaigns.find_one({'_id': newCampaignId})
    if not oldCampaignDoc:
        newCampaign['phoneNumbers'] = []
        mongo.db.campaigns.insert_one(newCampaign)
        return str(newCampaignId)

    newCampaign['phoneNumbers'] = oldCampaignDoc['phoneNumbers']

    if request.userId not in oldCampaignDoc['owners']:
        raise Exception("You are not authorized to update this campaign")

    mongo.db.campaigns.replace_one({'_id': newCampaignId}, newCampaign)
    return str(newCampaignId)

@app.route('/api/campaigns', methods=['GET'])
@users.loginRequired
def getCampaignsApi():
    try:
        campaignId = request.args.get("id", None, type=ObjectId)
        return json.dumps({'status': 'OK', 'result': getCampaigns()})
    except Exception as e:
        return json.dumps({'status': 'FAIL', 'error_message': str(e)})

def getCampaigns(campaignId):
    query = {
        '$or': [
            { 'owners': request.userId },
            { 'type': 'public' },
        ]
    }
    if campaignId:
        if not isinstance(campaignId, ObjectId):
            campaignId = ObjectId(campaignId)
        query['_id'] = campaignId

    campaigns = mongo.db.campaigns.find(query)
    def cleanCampaign(c):
        if not request.userId or request.userId not in c['owners']:
            for k in [ 'owners', 'billingOwner', 'expiresOn', 'phoneNumbers' ]:
                if k in c:
                    del c[k]
            c['isAdmin'] = False
        else:
            c['isAdmin'] = True
            serviceAccounts = set([ acct['_id'] for acct in mongo.db.users.find(
                {'_id': { '$in': c['owners'] }, 'type': 'service' }
            )])
            c['owners'] = [ o for o in c['owners'] if o not in serviceAccounts ]

        if 'stripeToken' in c:
            del c['stripeToken']

        for (k, v) in c.items():
            if isinstance(v, ObjectId):
                c[k] = str(v)
            if isinstance(v, list):
                for (i, sv) in enumerate(v):
                    if isinstance(sv, ObjectId):
                        v[i] = str(sv)
        return c
    return dict([ (str(c['_id']), cleanCampaign(c)) for c in campaigns ])

@app.route('/api/setStripeToken', methods=["POST"])
@users.loginRequired
def setStripeToken():
    try:
        return json.dumps({'status': 'OK', 'result': updateStripeToken(request.get_json())})
    except Exception as e:
        return json.dumps({'status': 'FAIL', 'error_message': str(e) })

def updateStripeToken(data):
    if 'campaign' not in data:
        raise Exception("No campaign specified")
    campaignId = data['campaign']
    if 'token' not in data:
        raise Exception("No stripe token specified")
    token = data['token']

    campaignDoc = mongo.db.campaigns.find_one({'_id': ObjectId(campaignId)})
    if not campaignDoc:
        raise Exception("Specified campaign does not exist")

    if 'stripeToken' in campaignDoc:
        customer = stripe.Customer.retrieve(campaignDoc['stripeToken'])
        customer.source = token
        customer.save()
    else:
        customer = stripe.Customer.create(
            source=token,
            description="{0} (id: {1})".format(campaignDoc['name'], campaignDoc['_id'])
        )

        mongo.db.campaigns.update_one(
            {'_id': ObjectId(campaignId)},
            { '$set': { 'stripeToken': customer.id } }
        )
    return True

@app.route('/api/buyPhoneNumber')
@users.loginRequired
def buyPhoneNumberApi():
    try:
        campaignId = request.args.get("campaignId", None, type=str)
        areaCode = request.args.get("areaCode", None, type=str)
        contains = request.args.get("contains", None, type=str)
        tollFree = request.args.get("tollFree", False, type=str)
        if tollFree == "true":
            tollFree = True
        else:
            tollFree = False

        return json.dumps({'status': 'OK', 'result':
            buyPhoneNumber(campaignId, areaCode, contains, tollFree)})
    except Exception as e:
        return json.dumps({'status': 'FAIL', 'error_message': str(e)})

def buyPhoneNumber(campaignId, areaCode, contains, tollFree):
    if not campaignId:
        raise Exception("No campaign id specified")
    campaignDoc = getCampaigns(campaignId)
    if not campaignDoc or campaignId not in campaignDoc:
        raise Exception("Specified campaign does not exist")
    campaignDoc = campaignDoc[campaignId]
    if not campaignDoc['isAdmin']:
        raise Exception("You are not authorized to buy phone numbers for this campaign")
    if not areaCode:
        raise Exception("Must specify the area code to get the new phone number from")
    if not campaignDoc['billingOwner']:
        raise Exception("No billing owner is set up for this campaign")
    if not campaignDoc['stripeToken']:
        raise Exception("No payment method is set up for this campaign")

    numberType = "tollfree" if tollFree else "local"
    args = {
        'contains': contains,
        'type': numberType,
        'area_code': areaCode,
        'country': 'US',
    }
    number = twilioClient.phone_numbers.search(**args)

    if number:
        number = number[0]
        number.purchase()
    try:
        mongo.db.campaigns.update_one(
            {'_id': ObjectId(campaignId)},
            {'$push': { 'phoneNumbers': number.phone_number } },
        )
    except Exception as e:
        number.delete()
        raise

    return number.phone_number

@app.route('/api/releasePhoneNumber')
@users.loginRequired
def releasePhoneNumberApi():
    phoneNumber = request.args.get("phoneNumber", None, type=str)
    try:
        return json.dumps({ 'status': 'OK', 'result': releasePhoneNumber(phoneNumber) })
    except Exception as e:
        return json.dumps({ 'status': 'FAIL', 'error_message': str(e) })

def releasePhoneNumber(phoneNumber):
    if not phoneNumber:
        raise Exception("No phone number specified")
    phoneNumber = phonenumbers.format_number(phonenumbers.parse(phoneNumber, 'US'),
        phonenumbers.PhoneNumberFormat.E164)

    campaignDoc = mongo.db.campaigns.find_one({'phoneNumbers': phoneNumber})
    if not campaignDoc:
        raise Exception("No campaign is associated with that phone number")

    if request.userId not in campaignDoc['owners']:
        raise Exception("You are not authorized to release this phone number")

    number = twilioClient.phone_numbers.list(phone_number=phoneNumber)
    if not number:
        raise Exception("Invalid number speicifed")
    number[0].delete()
    mongo.db.campaigns.update_one(
        {'_id': campaignDoc['_id']},
        {'$pull': { 'phoneNumbers': phoneNumber } })
    mongo.db.callscripts.delete_many({'phoneNumber': phoneNumber})
    return phoneNumber

