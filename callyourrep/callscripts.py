from bson import json_util
from bson.objectid import ObjectId
from callyourrep import app, mongo, utc, users
from datetime import datetime, timedelta
from flask import Flask, request, json, render_template, session, redirect, url_for
from flask.ext.pymongo import PyMongo, ASCENDING, DESCENDING
from postmark import PMMail
import requests
import jsonschema

callScriptSchema = {
    '$schema': 'https://www.callyourrep.us/schemas/callScriptSchema.json',
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
                        'pattern': '^[A-Fa-f\d]{24}$',
                    },
                ],
            },
        },
        'text': { 'type': 'string' },
        'recording': { 'type': 'string' },
        'expiresOn': { 'type': 'string', 'format': 'date-time' },
        'phoneNumber': { 'type': 'string', 'pattern': '^(\+?[1-9]\d{1,14})$' },
        'createdBy': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'submittedBy': { 'type': 'string' },
        'calls': { 'type': 'number' },
        'approvalCode': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'approvedBy': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'approved': { 'type': 'boolean' },
    },
    'required': [
        'campaign',
        'title',
        'appliesTo',
        'text',
        'phoneNumber',
    ]
}
@app.route('/schemas/callScriptSchema.json')
def getCallScriptSchema():
    return json.dumps(callScriptSchema)

@app.route('/api/callScripts', methods=['PUT'])
@users.loginRequired
def putCallScriptApi():
    try:
        newCallScript = request.get_json()
        newCallScript['approved'] = True
        return putCallScript(request.get_json())
    except Exception as e:
        return json.dumps({'status': 'FAIL', 'error_message': str(e)})

@app.route('/api/approveCallScript')
@users.loginRequired
def approveCallScriptApi():
    try:
        approvalCode = request.args.get("approval", None, ObjectId)
        if not approvalCode:
            raise Exception("No approval code specified")

        callScriptDoc = mongo.db.callscripts.find({'approvalCode': approvalCode})
        if not callScriptDoc:
            raise Exception("No call script has that approval code")

        if callScriptDoc['approved']:
            raise Exception("Call script already approved!")

        mongo.db.callscripts.update_one(
            {'_id': callScriptDoc['_id']},
            {'$set': { 'approved': True, 'approvedBy': request.userId }}
        )

        return json.dumps({'status': 'OK', 'result': 'Approved!'})
    except Exception as e:
        return json.dumps({'status': 'FAIL', 'error_message': str(e)})

@app.route('/api/suggestCallScript', methods=['POST'])
@users.loginOptional
def suggestCallScriptApi():
    try:
        newCallScript = request.get_json()
        if not request.userId:
            if 'g-recaptcha-response' not in newCallScript:
                raise Exception("No recaptcha response! Are you a robot!?")
            captchaResult = requests.post("https://www.google.com/recaptcha/api/siteverify",
                params = {
                    'secret': app.config['GOOGLE_RECAPTCHA_SECRET'],
                    'response': newCallScript['g-recaptcha-response'],
                    'remoteip': request.remote_addr },
                headers = {
                    'Referer': app.config['BASE_URL'],
                })

            if captchaResult.status_code != 200:
                raise Exception("Exception running captcha verification")
            captchaResultObj = captchaResult.json()
            if captchaResultObj['success'] == False:
                errorCodes = captchaResultObj.get("error-codes", "Unknown error")
                raise Exception("Exception running captcha verification: {}".format(errorCodes))
            del newCallScript['g-recaptcha-response']

        jsonschema.validate(newCallScript, callScriptSchema)
        newCallScript['approved'] = False
        newCallScript['approvalCode'] = str(ObjectId())
        res = putCallScript(request.get_json(), True)

        campaignDoc = mongo.db.campaigns.find_one({'_id': ObjectId(newCallScript['campaign'])})
        adminsCursor = mongo.db.users.find({'email': { '$in': campaignDoc['owners'] }})
        approvalLink = "{0}/api/approveCallScript?approval={1}".format(
            app.config['BASE_URL'], newCallScript['approvalCode'])

        emailText = """<p>A new call script has been submitted to your campaign!</p>
<p>You can approve this call script by going here <a href="{0}">{0}</a></p>.
<p><strong>Title:</strong> {1}</p>
<p><strong>Applies To:</strong> {2}</p>
<p><strong>Text:</strong> {3}</p>
<p><strong>Tags:</strong> {4}</p>
<p><strong>Submitted By:</strong> {5}
""".format(approvalLink,
           newCallScript['title'],
           ', '.join(newCallScript['appliesTo']),
           newCallScript['text'],
           ', '.join(newCallScript.get('tags', [])),
           newCallScript.get('submittedBy', ''))

        for admin in adminsCursor:
            message = PMMail(api_key = app.config['POSTMARK_API_KEY'],
                 subject = "New Suggested Call Script",
                 sender = "contact@callyourrep.us",
                 to = admin['email'],
                 html_body = emailText)
            message.send()
        return json.dumps({'status': 'OK', 'result': 'Submitted!'})

    except Exception as e:
        return json.dumps({'status': 'FAIL', 'error_message': str(e)})

def putCallScript(newCallScript, validated=False):
    if not validated:
        jsonschema.validate(newCallScript, callScriptSchema)
    newCallScriptId = ObjectId()
    if '_id' in newCallScript:
        newCallScript['_id'] = ObjectId(newCallScript['_id'])
        newCallScriptId = newCallScript['_id']

    newCallScript['campaign'] = ObjectId(newCallScript['campaign'])
    for i, v in enumerate(newCallScript['appliesTo']):
        try:
            v = ObjectId(v)
        except Exception:
            continue
        newCallScript['appliesTo'][i] = v

    oldCallScript = mongo.db.callscripts.find_one({'_id': newCallScriptId})
    if not oldCallScript:
        newCallScript['createdBy'] = request.userId
    else:
        newCallScript['createdBy'] = oldCallScript['createdBy']
        newCallScript['campaign'] = oldCallScript['campaign']

    campaignDoc = mongo.db.campaigns.find_one({'_id': newCallScript['campaign']})
    if not campaignDoc:
        raise Exception('Campaign {} not found'.format(newCallScript['campaign']))

    if not validated and request.userId not in campaignDoc['owners']:
        raise Exception('User not allowed to modify campaign {}'.format(
                newCallScript['campaign']))

    if newCallScript['phoneNumber'] not in campaignDoc['phoneNumbers']:
        raise Exception('Campaign {} does not own phone number {}'.format(
            newCallScript['campaign'], newCallScript['phoneNumber']))

    if not oldCallScript:
        mongo.db.callscripts.insert_one(newCallScript)
    else:
        mongo.db.callscripts.replace_one(
            {'_id': newCallScriptId},
            newCallScript,
        )

    return json.dumps({'status': 'OK', 'result': str(newCallScriptId) })

@app.route('/api/callScripts', methods=['GET'])
@users.loginOptional
def getCallScriptsApi():
    try:
        callScriptId = request.args.get('id', None, type=ObjectId)
        campaignId = request.args.get('campaign', None, type=ObjectId)
        searchTerms = request.args.get('searchTerms', None, type=str)

        return json.dumps({'status': 'OK',
            'result': getCallScripts(callScriptId, campaignId, searchTerms)})
    except Exception as e:
        return json.dumps({'status': 'FAIL', 'error_message': str(e)})

def getCallScripts(callScriptId, campaignId, searchTerms):
    query = {}
    if callScriptId:
        if not isinstance(callScriptId, ObjectId):
            callScriptId = ObjectId(callScriptId)
        query['_id'] = callScriptId

    if campaignId:
        if not isinstance(campaignId, ObjectId):
            campaignId = ObjectId(campaignId)
        campaignDoc = mongo.db.campaigns.find_one({'_id': campaignId})
        if not campaignDoc:
            raise Exception('Campaign {} does not exist'.format(campaignId))

        if campaignDoc['type'] == 'private' and \
            (not request.userId or request.userId not in campaignDoc['owners']):
            raise Exception('Campaign {} does not exist'.format(campaignId))

        query['campaign'] = campaignId
        if not request.userId or request.userId not in campaignDoc['owners']:
            query['approved'] = True
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
        query['approved'] = True

    if searchTerms:
        query['$text'] = {
            '$search': searchTerms,
            '$language': 'en',
            '$caseSensitive': False
        }

    cursor = mongo.db.callscripts.find(query)
    res = {}
    for c in cursor:
        for k in [ '_id', 'campaign', 'createdBy' ]:
            c[k] = str(c[k])
        for k in [ k for k in [ 'approvalCode' ] if k in c ]:
            del c[k]
        res[c['_id']] = c

    return res

