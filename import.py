import yaml
import pymongo
from bson.objectid import ObjectId
import requests
from lxml import etree
from StringIO import StringIO
import os
import base64
import phonenumbers

# Little lambda to get a prettified ordinal version of numbers for the "1st, 2nd, 3rd district"
def getOrdinal(num):
    return '%d%s' % (num, { 11: 'th', 12: 'th', 13: 'th' }.get(
        num % 100, { 1: 'st',2: 'nd',3: 'rd',}.get(
            num % 10, 'th')))

legislators = None
with open("legislators-current.yaml", "r") as yamlFp:
    legislators = yaml.load(yamlFp)

def resolveDistrict(term):
    districtName = term["state"]
    if term["type"] == "rep":
        districtName += "-{0}".format(term["district"])
        return ("cds/2016/{0}".format(districtName), districtName)
    elif term["type"] == "sen":
        return ("states/{0}".format(districtName),
                "{0}-{1}".format(districtName, term["state_rank"]))

client = pymongo.MongoClient(os.environ.get("MONGODB_URI", "mongodb://localhost:27017/callyourrep"))
db = client.get_default_database()

def writeLegislators():
    districts = db['contacts']
    districts.delete_many({'type': { '$in': [ 'sen', 'rep' ] }})
    for rep in legislators:
        currentTerm = rep["terms"][-1]
        districtPath, districtName = resolveDistrict(currentTerm)

        geoData = requests.get(
            "http://theunitedstates.io/districts/{0}/shape.geojson".format(districtPath))
        if geoData.status_code == 404:
            continue
        else:
            geoData.raise_for_status()
            geoData = geoData.json()

        if geoData["type"] == "Feature":
            geoData = geoData["geometry"]

        try:
            termType = currentTerm.get("type")
            fullTitle = ""
            if termType == 'sen':
                fullTitle = '{0} Senator from {1} ({2})'.format(
                    currentTerm["state_rank"].title(),
                    currentTerm['state'],
                    currentTerm.get("party"))
            elif termType == 'rep':
                fullTitle = "Representative from {0}'s {1} district ({2})".format(
                    currentTerm['state'],
                    getOrdinal(currentTerm['district']),
                    currentTerm.get("party"))

            picture = requests.get(
                "https://theunitedstates.io/images/congress/225x275/{0}.jpg".format(
                    rep["id"]["bioguide"]))
            if picture.status_code == 404:
                picture = None
                print "No picture found for {0}".format(districtName)
            else:
                picture.raise_for_status()
                picture = "data:image/jpeg;base64,{0}".format(base64.b64encode(picture.content))

            phoneNumber  = phonenumbers.format_number(
                phonenumbers.parse(currentTerm.get("phone"), 'US'),
                phonenumbers.PhoneNumberFormat.E164)

            districts.insert({
                'name': rep['name']['official_full'],
                'title': fullTitle,
                'type': currentTerm.get("type"),
                'visibility': 'public',
                'geoFence': geoData,
                'phoneNumber': phoneNumber,
                'image': picture,
                'campaign': ObjectId('5861961b2cb92874cb05a268'),
            })
        except Exception as e:
            print "Error writing {}: ({})".format(districtName, e)

        print "Wrote {}".format(districtName)

writeLegislators()
