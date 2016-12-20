from bson import json_util
from bson.objectid import ObjectId
from callyourrep import app, mongo, utc, users
from datetime import datetime, timedelta
from flask import Flask, request, json, render_template, session, redirect, url_for
from flask.ext.pymongo import PyMongo, ASCENDING, DESCENDING
import jsonschema

campaignSchema = {
    '$schema': 'https://www.callyourrep.us/static/campaignSchema.json',
    'type': 'object',
    'properties': {
        '_id': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'name': { 'type': 'string' },
        'type': { 'type': 'string', 'enum': [ 'public', 'private' ] },
        'phoneNumbers': {
            'type': 'array',
            'items': {
                'type': 'string',
                'pattern': '^\+?[1-9]\d{1,14}$',
            },
        },
        'owners': {
            'type': 'array',
            'items': {
                'type': 'string',
                'pattern': '^\+?[1-9]\d{1,14}$',
            }
        },
        'billingOwner': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'expiresOn': { 'type': 'string', 'format': 'date-time' },
    },
    'required': [
        'name',
        'type',
        'phoneNumbers',
    ]
}

@app.route('/api/campaigns', methods=['PUT'])
@users.loginRequired
def putCampaign():
    newCampaign = request.get_json()
    jsonschema.validate(newCampaign, campaignSchema)
    newCampaignId = ObjectId()
    if '_id' in newCampaign:
        newCampaign['_id'] = ObjectId(newCampaign['_id'])
        newCampaignId = newCampaign['_id']
    else:
        newCampaign['_id'] = newCampaignId

    oldCampaignDoc = mongo.db.campaigns.find_one({'_id': newCampaignId})
    if not oldCampaignDoc:
        mongo.db.campaigns.insert_one(newCampaign)
        return json.dumps({'status': 'OK', 'result': str(newCampaignId)})

    if 'owners' not in oldCampaignDoc:
        return json.dumps({'status': 'FAIL', 'error_message':
            "Can't update the global public campaign"})

    if request.userId not in oldCampaignDoc['owners']:
        return json.dumps({'status': 'FAIL', 'error_message':
            "You are not authorized to update this campaign"})

    del newCampaign['_id']
    mongo.db.campaigns.replace_one({'_id': newCampaignId}, newCampaign)
    return json_util.dumps({'status': 'OK', 'result': str(newCampaignId)})

@app.route('/api/campaigns', methods=['GET'])
@users.loginRequired
def getCampaigns():
    campaignId = request.args.get("id", None, type=ObjectId)
    query = {
        'owners': request.userId
    }
    if campaignId:
        query['_id'] = campaignId

    campaigns = mongo.db.campaigns.find(query)

    return json_util.dumps({'status': 'OK', 'result': [ c for c in campaigns ]})
