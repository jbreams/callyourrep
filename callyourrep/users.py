from bson.objectid import ObjectId
from callyourrep import app, mongo, utc
from datetime import datetime, timedelta
from flask import Flask, request, json, render_template, session, redirect, url_for
from flask.ext.pymongo import PyMongo, ASCENDING, DESCENDING
from functools import wraps
from passlib.hash import argon2
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Cipher import AES
from Crypto import Random
from Crypto.Hash import HMAC, SHA512

import base64
import requests

class SecretCipher:
    secretKey = PBKDF2(app.config['DB_SECRET_KEY'], app.config['BASE_URL'], dkLen=32, count=10000)
    def __init__(self):
        pass

    def encrypt(self, val):
        iv = Random.new().read(AES.block_size)
        cipher = AES.new(self.secretKey, AES.MODE_CBC, iv)
        paddingLen = AES.block_size - (len(val) % AES.block_size)
        msg = val + (chr(paddingLen) * paddingLen)
        return base64.b64encode(iv + cipher.encrypt(msg))

    def decrypt(self, val):
        cipherText = base64.b64decode(val)
        iv = cipherText[:AES.block_size]
        cipher = AES.new(self.secretKey, AES.MODE_CBC, iv)
        plainText = cipher.decrypt(cipherText[AES.block_size:])
        return plainText[:-ord(plainText[-1])]

userSchema = {
    '$schema': 'https://www.callyourrep.us/static/userSchema.json',
    'type': 'object',
    'properties': {
        '_id': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'type': { 'type': 'string', 'enum': [ 'service', 'user' ] },
        'email': { 'type': 'string', 'format': 'email' },
        'password': { 'type': 'string' },
        'campaign': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'secretKey': { 'type': 'string' },
        'createdBy': { 'type': 'string', 'pattern': '^[A-Fa-f\d]{24}$' },
        'note': { 'type': 'string' },
    },
}

def checkServiceLogin():
    if 'Authorization' not in request.headers:
        return False
    if not request.headers['Authorization'].startswith("CYR "):
        return False

    accountId = None
    try:
        if 'Date' not in request.headers:
            raise Exception("Must provide Date header to use service account authentication")
        authData = requst.headers['Authorization'][4:].split(":",2)
        if len(authData) != 2:
            raise Exception("Not enough data for authentication")
        accountId = ObjectId(authData[0])
        accountDoc = mongo.db.users.find_one({'_id': accountId, 'type': 'service'})
        if not accountDoc:
            raise Exception('No account matches your account id')

        cipher = SecretCipher()
        secretKey = cipher.decrypt(accountDoc['secretKey'])
        hmac = HMAC.new(secretKey, digestmod=SHA512)
        hmac.update(request.method)
        hmac.update(request.url)
        hmac.update(request.headers['Date'])
        checksum = base64.b64encode(hmac.digest())
        if authData[2] == checksum:
            mongo.db.users.update_one(
                {'_id': accountId},
                {'$set': { 'lastLogin': datetime.now(utc) }}
            )
            setattr(request, 'userId', accountID)
            setattr(request, 'userOwnerOf', [ accountDoc['campaign'] ])

            return True
        raise Exception("Authentication failed")

    except Exception as e:
        if accountID:
            mongo.db.users.update_one(
                {'_id': accountId},
                {'$set': { 'lastFailedLogin': datetime.now(utc) }}
            )
        raise

def createSessionForUser(userDoc):
    sessionDoc = {
        '_id': ObjectId(),
        'user': userDoc['_id'],
        'started': datetime.now(utc),
    }
    mongo.db.sessions.insert_one(sessionDoc)
    session["sessionId"] = str(sessionDoc['_id'])

def loginRequired(f):
    @wraps(f)

    def decorated_function(*args, **kwargs):
        isServiceLogin = False
        try:
            isServiceLogin = checkServiceLogin()
        except Exception as e:
            return json.dumps({'status': 'FAIL', 'error_message': str(e) })
        if isServiceLogin:
            return f(*args, **kwargs)

        if not session.get("sessionId"):
            return redirect(url_for('signin',
                next=request.url, error="You must login to view this page"))

        sessionDoc = mongo.db.sessions.find_one({'_id': ObjectId(session.get("sessionId"))})
        if not sessionDoc:
            return redirect(url_for('signin',
                next=request.url, error="Invalid session. You must login to view this page"))
        if 'ended' in sessionDoc:
            return redirect(url_for('signin',
                next=request.url, error="Session expired. You must login to view this page"))
        setattr(request, 'userId', sessionDoc['user'])

        campaignsCursor = mongo.db.campaigns.find({'owners': sessionDoc['user']})
        campaigns = [ c['_id'] for c in campaignsCursor ]
        setattr(request, 'userOwnerOf', campaigns)

        return f(*args, **kwargs)
    return decorated_function

def loginOptional(f):
    @wraps(f)

    def decorated_function(*args, **kwargs):
        setattr(request, 'userId', None)
        setattr(request, 'userOwnerOf', [])
        if not session.get("sessionId"):
            return f(*args, **kwargs)

        sessionDoc = mongo.db.sessions.find_one({'_id': ObjectId(session.get("sessionId"))})
        if not sessionDoc or 'ended' in sessionDoc:
            return f(*args, **kwargs)
        setattr(request, 'userId', sessionDoc['user'])

        campaignsCursor = mongo.db.campaigns.find({'owners': sessionDoc['user']})
        campaigns = [ c['_id'] for c in campaignsCursor ]
        setattr(request, 'userOwnerOf', campaigns)

        return f(*args, **kwargs)
    return decorated_function

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'GET':
        return render_template('signin.html',
            googleAPIKey=app.config['GOOGLE_API_KEY'],
            googleAnalyticsKey=app.config['GOOGLE_ANALYTICS_KEY'],
            googleRecaptchaKey=app.config['GOOGLE_RECAPTCHA_KEY'],
            nextUrl=request.args.get('next', ''),
            errorText=None)
    try:
        redirectTo = request.form.get('next', url_for('manage'))
        if request.form.has_key("signin"):
            userDoc = mongo.db.users.find_one({'email': request.form.get("signinEmail", type=str)})
            if not userDoc:
                raise Exception("Couldn't find a user with a matching email address")
            if not argon2.verify(request.form.get("signinPassword", type=str), userDoc["password"]):
                raise Exception("Incorrect password")

            createSessionForUser(userDoc)

            return redirect(redirectTo)
        elif request.form.has_key("signup"):
            if request.form.get("signupPassword") != request.form.get("signupPassword2"):
                raise Exception("Passwords do not match");
            if not request.form.get("signupEmail"):
                raise Exception("Email must not be empty to sign up")
            if request.form.get("signupPassword", type=str) == "":
                raise Exception("Password must not be empty to sign up")
            captchaResult = requests.post("https://www.google.com/recaptcha/api/siteverify",
                params = {
                    'secret': app.config['GOOGLE_RECAPTCHA_SECRET'],
                    'response': request.form.get('g-recaptcha-response'),
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

            userDoc = {
                '_id': ObjectId(),
                'type': 'user',
                'email': request.form.get('signupEmail', type=str),
                'password': argon2.hash(request.form.get('signupPassword', type=str)),
                'created': datetime.now(utc),
            }
            mongo.db.users.insert_one(userDoc)
            createSessionForUser(userDoc)
            return redirect(redirectTo)
    except Exception as e:
        return render_template('signin.html',
        googleAPIKey=app.config['GOOGLE_API_KEY'],
        googleAnalyticsKey=app.config['GOOGLE_ANALYTICS_KEY'],
        googleRecaptchaKey=app.config['GOOGLE_RECAPTCHA_KEY'],
        errorText=str(e))

@app.route('/signout')
@loginRequired
def signout():
    mongo.db.sessions.update_one(
        {'_id': ObjectId(session.get("sessionId"))},
        {'$set': { 'ended': datetime.now(utc) } }
    )
    return redirect('/')

@app.route('/api/user')
@loginRequired
def getUsersApi():
    userId = request.args.get("id", None, ObjectId)
    email = request.args.get("email", None, str)
    try:
        return json.dumps({'status': 'OK', 'result': getUser(email, userId) })
    except Exception as e:
        return json.dumps({'status': 'FAIL', 'error_message': str(e) })

def getUser(email, userId = None):
    userDoc = None
    if email:
        userDoc = mongo.db.users.find_one({'email': email, 'type': 'user'})
        if not userDoc:
            raise Exception("No user found with that email address")
    elif userId:
        if not isinstance(userId, ObjectId):
            userId = ObjectId(userId)
        userDoc = mongo.db.users.find_one({'_id': userId, 'type': 'user'})
        if not userDoc:
            raise Exception("No user found with that id")
    else:
        raise Exception("Must provide either a user id or email to lookup")

    return { '_id': str(userDoc['_id']), 'email': userDoc['email'] }

@app.route('/api/serviceAccounts', methods=['POST'])
@loginRequired
def createServiceAccount():
    try:
        req = request.get_json()
        if 'campaign' not in req:
            raise Exception("Must specify campaign ID to create a service account")
        campaignId = ObjectId(req['campaign'])
        if campaignId not in request.userOwnerOf:
            raise Exception("You are not an owner of that campaign. Cannot create service account.")

        secretKey = Random.new().read(20).encode('hex')
        cipher = SecretCipher()

        newAccountId = ObjectId()
        newAccount = {
            '_id': newAccountId,
            'type': 'service',
            'email': 'Service Account {}'.format(newAccountId),
            'createdBy': request.userId,
            'createdAt': datetime.now(utc),
            'secretKey': cipher.encrypt(secretKey),
            'campaign': campaignId,
            'note': req.get('note', ''),
        }
        mongo.db.users.insert_one(newAccount)
        mongo.db.campaigns.update_one(
            { '_id': campaignId },
            { '$push': { 'owners': newAccountId }},
        )
        newAccount['secretKey'] = secretKey
        for (k, v) in newAccount.items():
            if isinstance(v, ObjectId):
                newAccount[k] = str(v)

        return json.dumps({'status': 'OK', 'result': newAccount})

    except Exception as e:
        raise
        return json.dumps({'status': 'FAIL', 'error_message': str(e)})

@app.route('/api/serviceAccounts', methods=['GET'])
@loginRequired
def getServiceAccountsApi():
    try:
        campaign = request.args.get('campaign', None, ObjectId)
        return json.dumps({'status': 'OK', 'result': getServiceAccounts(campaign)})
    except Exception as e:
        raise
        return json.dumps({'status': 'FAIL', 'error_message': str(e)})

def getServiceAccounts(campaign):
    if not campaign:
        raise Exception("Must specify campaign ID to list service accounts")

    if campaign not in request.userOwnerOf:
        raise Exception("You are not authorized to get list of service accounts")

    accountCurs = mongo.db.users.find({'type': 'service', 'campaign': campaign})
    cipher = SecretCipher()
    def cleanAccount(c):
        for k in ['_id', 'campaign', 'createdBy' ]:
            c[k] = str(c[k])
        c['secretKey'] = cipher.decrypt(c['secretKey'])
        return c
    accounts = dict((str(c['_id']), cleanAccount(c)) for c in accountCurs)
    return  accounts

@app.route('/api/serviceAccounts', methods=['DELETE'])
@loginRequired
def deleteServiceAccount():
    try:
        requestData = request.get_json()
        if 'account' not in requestData:
            raise Exception("Must specify id of account to delete")
        account = ObjectId(requestData['account'])

        accountDoc = mongo.db.users.find_one({'_id': account, 'type': 'service'})
        if not accountDoc:
            raise Exception("No account found with that id")

        if accountDoc['campaign'] not in request.userOwnerOf:
            raise Exception("You are not authorized to delete this service account")

        mongo.db.campaigns.update_one(
            {'_id': accountDoc['campaign']},
            {'$pull': { 'owners': account }}
        )

        mongo.db.users.delete_one({'_id': account})
        return json.dumps({'status': 'OK', 'result': str(account)})
    except Exception as e:
        raise
        return json.dumps({'status': 'FAIL', 'error_message': str(e)})

