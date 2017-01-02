from bson import json_util
from bson.objectid import ObjectId
from callyourrep import app, mongo, utc, users
from datetime import datetime, timedelta
from flask import Flask, request, json, render_template, session, redirect, url_for
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
        if 'campaign' not in contact:
            return contact['createdBy'] == request.userId

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

@app.route('/api/contacts', methods=['GET'])
@users.loginOptional
def getContactsApi():
    try:
        contactId = request.args.get('id', None, type=ObjectId)
        lat = request.args.get('lat', None, type=float)
        lng = request.args.get('lng', None, type=float)
        campaignId = request.args.get('campaign', None, type=ObjectId)

        return json.dumps({'status': 'OK',
            'result': getContacts(contactId, lat, lng, campaignId)})
    except Exception as e:
        return json.dumps({'status': 'FAIL', 'error_message': str(e)})

def getContacts(contactId, lat, lng, campaignId):
    checkPerms = CheckContactForUser()
    if campaignId and not isinstance(campaignId, ObjectId):
        campaignId = ObjectId(campaignId)

    if contactId:
        if not isinstance(contactId, ObjectId):
            contactId = ObjectId(contactId)
        contactDoc = mongo.db.contacts.find_one({'_id': contactId})
        if not contactDoc:
            return json.dumps({'status': 'FAIL', 'error_message':
                'Contact with the id {} does not exist'.format(contactId)})
        if not checkPerms(contactDoc):
            return json.dumps({'status': 'FAIL', 'error_message':
                'Not authorized to access this contact'})

        return json.dumps({'status': 'OK', 'result': contactId})

    query = {}
    if not request.userId:
        query['visibility'] = "public"

    if lat and lng:
        query = {
            'geoFence': {
                '$geoIntersects': {
                    'type': 'Point',
                    'coordinates': [ lng, lat ],
                }
            }
        }

        if campaignId:
            query['campaign'] = campaignId

    elif campaignId:
        query = { 'campaign': campaignId }

    contactCursor = mongo.db.contacts.find(query)
    def cleanContact(c):
        for (k, v) in c.items():
            if isinstance(v, ObjectId):
                c[k] = str(v)
        return c
    contacts = dict([ (str(c['_id']), cleanContact(c)) for c in contactCursor if checkPerms(c) ])
    return contacts
