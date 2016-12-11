# callyourrep

This is a project to help you find and call your members of congress! It's currently a work in progress.

Thanks so much for contributing!  To get up-and-building, there are a few things you'll have to do.

Install dependencies
====================

If you are developing on OS X, you will need to get the XCode developer tools
```xcode-select --install```

Download the latest version of MongoDB:
https://www.mongodb.com/download

Callyourrep requires several python libraries:

```
> sudo pip install flask
> sudo pip install flask_pymongo
> sudo pip install flask_sslify
> sudo pip install lxml
> sudo pip install requests
> sudo pip install phonenumbers
> sudo pip install pyyaml
> sudo pip install twilio
```

Set up app configurations
=========================

The application's configurations will be automatically set from variables in
your shell environment. You will need to register with the following services
and store your keys in environment variables:

1. Google Maps

Google requires the use of an API key for applications that use Google Maps.
You'll need to have a Google login to get an API key:
https://developers.google.com/maps/documentation/javascript/get-api-key

Store your Google API key in an environment variable called GOOGLE_API_KEY:
```
> export GOOGLE_API_KEY="your_key"
```

2. Google Analytics

Add your google analytics key to your environment:
```
> export GOOGLE_ANALYTICS_KEY="your_key"
```

3. Twilio

Twilio powers callyourrep's voice over IP services. You'll need to sign up for
Twilio here:
https://www.twilio.com/try-twilio

Once you have an account you can retrieve your auth token and sid here:
https://www.twilio.com/console

Store them in environment variables:
```
> export TWILIO_ACCOUNT_SID="your_key"
> export TWILIO_AUTH_TOKEN="your_key"
```

Next, you'll need to purchase a Twilio phone number to use to make outgoing calls.
Once you do that, store it here:
```
> export TWILIO_OUTGOING_NUMBER="1234567890"
```

Finally, generate a new app id for this project, and then add it to your environment:
```
> export TWILIO_APP_SID="your_key"
```

Seeding the database
====================

To seed the database, start up a mongod on port 27107, and run the import script:
```
> ./mongod
> python import.py
```

You'll also need to create a topics collection in the app database and create a
text index on it.  First, open the mongo shell:
```
> ./mongo
shell> use app
shell> db.topics.createIndex({ text: "text" })
```

You can then insert your own call scripts into the app.topics collection by expressing
them as documents of the following form:
```
{
   title : "The Best Issue Ever",
   text : "Hey there <Senator> I just wanted to tell you about this topic",
   useCount : 0,
   searchCount : 0,
   callCount : 0
}
```

Running the server
==================

Start up your mongod on port 27017, then run the server:
```
> ./mongod
> python app.py
```

