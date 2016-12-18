from bson.objectid import ObjectId
from callyourrep import app, mongo, utc
from datetime import datetime, timedelta
from flask import Flask, request, json, render_template, session, redirect, url_for
from flask.ext.pymongo import PyMongo, ASCENDING, DESCENDING
from functools import wraps
from passlib.hash import argon2
import requests

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
        return f(*args, **kwargs)
    return decorated_function

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'GET':
        return render_template('signin.html',
            googleAPIKey=app.config['GOOGLE_API_KEY'],
            googleAnalyticsKey=app.config['GOOGLE_ANALYTICS_KEY'],
            googleRecaptchaKey=app.config['GOOGLE_RECAPTCHA_KEY'],
            errorText=None)
    try:
        redirectTo = request.args.get('next', url_for('manage'))
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
                pprint(captchaResultObj)
                errorCodes = captchaResultObj.get("error-codes", "Unknown error")
                raise Exception("Exception running captcha verification: {}".format(errorCodes))

            userDoc = {
                '_id': ObjectId(),
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
