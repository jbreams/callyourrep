from bson import json_util
from bson.objectid import ObjectId
from callyourrep import app, mongo, utc, users
from datetime import datetime, timedelta
from flask import Flask, request, json, session, abort
from flask.ext.pymongo import PyMongo, ASCENDING, DESCENDING
import jsonschema

contactSchema = {
    '$schema': 'https://www.callyourrep.us/schema/contactSchema.json',
    'type': 'object',
    'properties': {
        '_id': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'name': { 'type': 'string' },
        'title': { 'type': 'string' },
        'type': { 'type': 'string', 'enum': ['stateRep', 'stateSen', 'rep', 'sen', 'custom'] },
        'visibility': { 'type': 'string', 'enum': [ 'public', 'private', ] },
        'campaign': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'createdBy': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'phoneNumber': { 'type': 'string', 'pattern': '^(\+?[1-9]\d{1,14})$' },
        'image': { 'type': 'string' },
        'contactMethods': {
            'type': 'array',
            'items': {
                'type': 'object',
            }
        },
        'geoFence': { 'type': 'object' },
        'calls': { 'type': 'number' },
    },
    'required': [
        'name',
        'title',
        'type',
        'visibility',
        'phoneNumber',
    ],
}
@app.route('/schemas/contactSchema.json')
def getCpntactSchema():
    return json.dumps(contactSchema)

class CheckContactForUser:
    def __init__(self):
        self.cache = {}
    def __call__(self, contact):
        if contact['visibility'] == 'public':
            return True

        if contact['campaign'] not in self.cache:
            campaignDoc = mongo.db.campaigns.find_one({'_id': contact['campaign']})
            if not campaignDoc:
                return False
            self.cache[contact['campaign']] = campaignDoc

        campaign = self.cache[contact['campaign']]
        if campaign['type'] == 'public':
            return True
        return contact['campaign'] in request.userOwnerOf

@app.route('/api/contacts', methods=['PUT'])
@users.loginRequired
def putContactApi():
    try:
        return json.dumps({'status': 'OK', 'result': putContact(request.get_json())})
    except Exception as e:
        return json.dumps({'status': 'FAIL', 'error_message': str(e)})

def putContact(newContact):
    jsonschema.validate(newContact, contactSchema)
    newContactId = ObjectId()
    if '_id' in newContact:
        newContact['_id'] = ObjectId(newContact['_id'])
        newContactId = newContact['_id']
    else:
        newContact['_id'] = newContactId

    newContact['campaign'] = ObjectId(newContact['campaign'])
    if 'geoFence' in newContact:
        geoFence = newContact['geoFence']
        if geoFence['type'] == 'Feature':
            geoFence = geoFence['geometry']
        newContact['geoFence'] = geoFence

    oldContactDoc = mongo.db.contacts.find_one({'_id': newContactId})
    if not oldContactDoc:
        newContact['createdBy'] = request.userId
        mongo.db.contacts.insert_one(newContact)
        return str(newContactId)

    for k in ['createdBy', 'campaign']:
        if k in oldContactDoc:
            newContact[k] = oldContactDoc[k]

    checkPerms = CheckContactForUser()
    if not checkPerms(oldContactDoc):
        raise Exception('You are not authorized to update this contact')

    mongo.db.contacts.replace_one({'_id': newContactId}, newContact)
    return str(newContactId)

@app.route('/api/contacts', methods=['DELETE'])
@users.loginRequired
def deleteContactApi():
    try:
        reqData = request.get_json()
        contactId = reqData.get('id', None)
        return json.dumps({'status': 'OK',
            'result': deleteContact(contactId)})
    except Exception as e:
        return json.dumps({'status': 'FAIL', 'error_message': str(e)})

def deleteContact(contactId):
    if not contactId:
        raise Exception('Missing contact id')
    if not isinstance(contactId, ObjectId):
        contactId = ObjectId(contactId)

    contactDoc = mongo.db.contacts.find_one({'_id': contactId})
    if not contactDoc:
        raise Exception('Contact {} does not exist!'.format(contactId))

    if contactDoc['campaign'] not in request.userOwnerOf:
        raise Exception('User not allowed to modify campaign {}'.format(contactDoc['campaign']))

    mongo.db.contacts.delete_one({'_id': contactDoc['_id']})
    return str(contactDoc['_id'])

@app.route('/api/contacts', methods=['GET'])
@users.loginOptional
def getContactsApi():
    try:
        contactId = request.args.get('id', None, type=ObjectId)
        lat = request.args.get('lat', None, type=float)
        lng = request.args.get('lng', None, type=float)
        campaignId = request.args.get('campaign', None, type=ObjectId)
        callScriptId = request.args.get('callscript', None, type=ObjectId)
        contactType = request.args.get('type', None, type=str)
        search = request.args.get('search', None, type=str)

        return json.dumps({'status': 'OK',
            'result': getContacts(contactId, lat, lng, campaignId, contactType, search, callScriptId)})
    except Exception as e:
        return json.dumps({'status': 'FAIL', 'error_message': str(e)})

def getContacts(contactId=None, lat=None, lng=None, campaignId=None, contactType=None, search=None, callScriptId=None):
    checkPerms = CheckContactForUser()
    if callScriptId:
        callScriptDoc = mongo.db.callscripts.find_one(callScriptId)
        if not callScriptDoc:
            raise Exception("Cannot find call script {}".format(callScriptId))
        contactType = callScriptDoc['appliesTo']
    if campaignId and not isinstance(campaignId, ObjectId):
        campaignId = ObjectId(campaignId)

    if contactId:
        if not isinstance(contactId, ObjectId):
            contactId = ObjectId(contactId)
        contactDoc = mongo.db.contacts.find_one({'_id': contactId})
        if not contactDoc:
            raise Exception('Contact with the id {} does not exist'.format(contactId))
        if not checkPerms(contactDoc):
            raise Exception('Not authorized to access this contact')

        return cleanContact(contactDoc)

    query = {}
    if not request.userId:
        query['visibility'] = "public"

    if lat and lng:
        query = {
            'geoFence': {
                '$geoIntersects': {
                    '$geometry': {
                        'type': 'Point',
                        'coordinates': [ lng, lat ],
                    }
                }
            }
        }

        if campaignId:
            query['campaign'] = campaignId

    elif campaignId:
        query['campaign'] = campaignId

    if contactType and contactType != 'all':
        if isinstance(contactType, list):
            query['type'] = { '$in': contactType }
        else:
            query['type'] = contactType

    if search:
        query['$text'] = {
            '$search': search,
            '$language': 'en',
            '$caseSensitive': False,
        }

    contactCursor = mongo.db.contacts.find(query)
    def cleanContact(c):
        for (k, v) in c.items():
            if isinstance(v, ObjectId):
                c[k] = str(v)
        return c
    contacts = dict([ (str(c['_id']), cleanContact(c)) for c in contactCursor if checkPerms(c) ])
    return contacts

