from bson import json_util
from bson.objectid import ObjectId
from callyourrep import app, mongo, utc, users
from datetime import datetime, timedelta
from flask import Flask, request, json, render_template, session, redirect, url_for
from flask.ext.pymongo import PyMongo, ASCENDING, DESCENDING
import jsonschema

callScriptSchema = {
    '$schema': 'https://www.callyourrep.us/static/campaignSchema.json',
    'type': 'object',
    'properties': {
        '_id': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'campaign': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'title': { 'type': 'string' },
        'tags': {
            'type': 'array',
            'items': { 'type': 'string' },
        },
        'appliesTo': {
            'type': 'array',
            'items': {
                'anyOf': [
                    {
                        'type': 'string',
                        'enum': [
                            'stateRep',
                            'stateSen',
                            'rep',
                            'sen',
                        ],
                    },
                    {
                        'type': 'string',
                        'pattern': '^\+?[1-9]\d{1,14}$',
                    },
                ],
            },
        },
        'text': { 'type': 'string' },
        'recording': { 'type': 'string' },
        'expiresOn': { 'type': 'string', 'format': 'date-time' },
        'phoneNumber': { 'type': 'string', 'pattern': '^(\+?[1-9]\d{1,14})$' },
        'createdBy': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
    },
    'required': [
        'campaign',
        'title',
        'appliesTo',
        'text',
    ]
}

@app.route('/api/callScripts', methods=['PUT'])
@users.loginRequired
def putCallScript():
    newCallScript = request.get_json()
    jsonschema.validate(newCallScript, callScriptSchema)
    newCallScriptId = ObjectId()
    if '_id' in newCallScript:
        newCallScript['_id'] = ObjectId(newCallScript['_id'])
        del newCallScript['_id']

    newCallScript['campaign'] = ObjectId(newCallScript['campaign'])
    newCallScript['createdBy'] = ObjectId(newCallScript['createdBy'])

    campaignDoc = mongo.db.campaigns.find_one({'_id': newCallScript['campaign']})
    if not campaignDoc:
        return json.dumps({'status': 'FAIL', '_id': newCallScriptId,
            'error_message': 'Campaign {} not found'.format(newCallScript['campaign'])})
    if 'owners' in campaignDoc and request.userId not in campaignDoc['owners']:
        return json.dumps({'status': 'FAIL', '_id': newCallScriptId,
            'error_message': 'User not allowed to modify campaign {}'.format(
                newCallScript['campaign'])})
    if 'phoneNumber' in newCallScript and \
            newCallScript['phoneNumber'] not in campaignDoc['phoneNumbers']:
        return json.dumps({'status': 'FAIL', '_id': newCallScriptId,
            'error_message': 'Campaign {} does not own phone number {}'.format(
                newCallScript['campaign'], newCallScript['phoneNumber'])})

    if 'owners' not in campaignDoc:
        oldScriptDoc = mongo.db.callscripts.find_one({'_id': newCallScriptId})
        if oldScriptDoc and request.userId != oldScriptDoc['createdBy']:
            return json.dumps({'status': 'FAIL', '_id': newCallScriptId,
                'error_message': 'Cannot update call script you did not create' })

    oldCallScript = mongo.db.callscripts.find_one({'_id': newCallScriptId})
    if not oldCallScript:
        newCallScript['createdBy'] = request.userId
    else:
        newCallScript['createdBy'] = oldCallScript['createdBy']
        newCallScript['campaign'] = oldcallScript['campaign']

    mongo.db.callscripts.replace_one(
        {'_id': newCallScriptId},
        newCallScript,
    )

    return json.dumps({'status': 'OK', 'result': str(newCallScriptId) })

@app.route('/api/callScripts', methods=['GET'])
@users.loginOptional
def getCallScripts():
    callScriptId = request.args.get('id', None, type=ObjectId)
    campaignId = request.args.get('campaign', None, type=ObjectId)
    searchTerms = request.args.get('searchTerms', None, type=str)

    query = {}
    if callScriptId:
        query['_id'] = callScriptId

    if campaignId:
        campaignDoc = mongo.db.campaigns.find_one({'_id': campaignId})
        if not campaignDoc:
            return json.dumps({'status': 'FAIL',
                'error_message': 'Campaign {} does not exist}'.format(campaignId)})

        if campaignDoc['type'] == 'private' and \
            (not request.userId or request.userId not in campaignDoc['owners']):
            return json.dumps({'status': 'FAIL',
                'error_message': 'Campaign {} does not exist}'.format(campaignId)})

        query['campaign'] = campaignId
    else:
        campaignCursor = None
        if request.userId:
            campaignCursor = mongo.db.campaigns.find({'$or': [
                { 'type': 'public' },
                { 'type': 'private', 'owners': request.userId },
            ]})
        else:
            campaignCursor = mongo.db.campaigns.find({'type': 'public'})
        campaignIds = []
        for c in campaignCursor:
            campaignIds.append(c['_id'])
        query['campaign'] = { '$in': campaignIds }

    if searchTerms:
        query['$text'] = {
            '$search': searchTerms,
            '$language': 'en',
            '$caseSensitive': False
        }

    cursor = mongo.db.callscripts.find(query)
    res = {
        'status': 'OK',
        'result': []
    }
    for c in cursor:
        c['_id'] = str(c['_id'])
        c['campaign'] = str(c['campaign'])
        res['result'].append(c)

    return json_util.dumps(res)

