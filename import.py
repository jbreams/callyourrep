import yaml
import pymongo
import requests
import geojson

legislators = None
with open("legislators-current.yaml", "r") as yamlFp:
    legislators = yaml.load(yamlFp)

client = pymongo.MongoClient('mongodb://localhost:27017')
db = client['callyourrep']

districts = db['districts']
districts.drop();
districts.create_index([('district', pymongo.GEOSPHERE)])
def resolveDistrict(term):
    districtName = term["state"]
    if term["type"] == "rep":
        districtName += "-{0}".format(term["district"])
        return ("cds/2016/{0}".format(districtName), districtName)
    elif term["type"] == "sen":
        return ("states/{0}".format(districtName),
                "{0}-{1}".format(districtName, term["state_rank"]))

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
        districts.insert({
            '_id': districtName,
            'district': geoData,
            'repName': rep["name"]["official_full"],
            'phone': currentTerm.get("phone"),
            'contactForm': currentTerm.get("contact_form"),
            'pictureId': rep["id"]["bioguide"],
            'party': currentTerm.get("party"),
            'type': currentTerm.get("type"),
        })
    except Exception as e:
        print "Error writing {}: ({})".format(districtName, e)

    print "Wrote {}".format(districtName)

