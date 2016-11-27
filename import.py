import yaml
import pymongo
import requests
from lxml import etree
from StringIO import StringIO

# Little lambda to get a prettified ordinal version of numbers for the "1st, 2nd, 3rd district"
def getOrdinal(num):
    return '%d%s' % (num, { 11: 'th', 12: 'th', 13: 'th' }.get(
        num % 100, { 1: 'st',2: 'nd',3: 'rd',}.get(
            num % 10, 'th')))

legislators = None
with open("legislators-current.yaml", "r") as yamlFp:
    legislators = yaml.load(yamlFp)

committees = {}
with open('committees-current.yaml', 'r') as yamlFp:
    rawCommittees = yaml.load(yamlFp)
    for committee in rawCommittees:
        committees[committee['thomas_id']] = {
            'name': committee['name'],
            'url': committee['url'],
            'phone': committee.get('phone', None),
            'jurisdiction': committee.get('jurisdiction', None),
        }

        if 'subcommittees' in committee:
            for sub in committee['subcommittees']:
                committees[committee['thomas_id'] + sub['thomas_id']] = {
                    'name': "{0} sub-committee on {1}".format(
                        committee['name'], sub['name']),
                    'url': committee['url'],
                    'phone': committee.get('phone', None),
                }

memberToCommittee = {}
with open('committee-membership-current.yaml', 'r') as yamlFp:
    committeeMembership = yaml.load(yamlFp)
    for (committee, members) in committeeMembership.items():
        for member in members:
            if member['bioguide'] not in memberToCommittee:
                memberToCommittee[member['bioguide']] = [
                        { 'committee': committee, 'rank': getOrdinal(member['rank']) }
                ]
            else:
                memberToCommittee[member['bioguide']].append(
                    {'committee': committee, 'rank': getOrdinal(member['rank']) })


client = pymongo.MongoClient('mongodb://localhost:27017')
db = client['callyourrep']

def resolveDistrict(term):
    districtName = term["state"]
    if term["type"] == "rep":
        districtName += "-{0}".format(term["district"])
        return ("cds/2016/{0}".format(districtName), districtName)
    elif term["type"] == "sen":
        return ("states/{0}".format(districtName),
                "{0}-{1}".format(districtName, term["state_rank"]))

def getBio(bioguideId):
    rawGuideHTML = requests.get(
        "http://bioguide.congress.gov/scripts/biodisplay.pl?index=" + bioguideId)
    parser = etree.HTMLParser()
    guideXmlTree = etree.parse(StringIO(rawGuideHTML.text), parser)
    return guideXmlTree.xpath('/html/body/table[2]/tr/td[2]/p/text()')[0].replace(
        '\n', '').replace('\r', '')

def writeLegislators():
    districts = db['districts']
    districts.drop();
    districts.create_index([('district', pymongo.GEOSPHERE)])
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

            districts.insert({
                '_id': districtName,
                'district': geoData,
                'repName': rep["name"]["official_full"],
                'fullTitle': fullTitle,
                'phone': currentTerm.get("phone"),
                'contactForm': currentTerm.get("contact_form"),
                'mailingAddress': currentTerm.get("address"),
                'fax': currentTerm.get('fax'),
                'pictureId': rep["id"]["bioguide"],
                'party': currentTerm.get("party"),
                'type': currentTerm.get("type"),
                'bio': getBio(rep['id']['bioguide']),
                'committees': memberToCommittee[rep['id']['bioguide']],
            })
        except Exception as e:
            print "Error writing {}: ({})".format(districtName, e)

        print "Wrote {}".format(districtName)

writeLegislators()
committeesColl = db['committees']
committeesColl.drop()
for (idfield, data) in committees.items():
    data['_id'] = idfield
    committeesColl.insert(data)
