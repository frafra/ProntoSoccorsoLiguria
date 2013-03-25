#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright 2013 Francesco Frassinelli <fraph24@gmail.com>

import conf

import sys
if sys.version_info >= (3, 0):
    from html.parser import HTMLParser
    from urllib.error import HTTPError
    from urllib.request import urlopen
    from urllib.parse import quote, urlencode
    import functools
    def u(string):
        return string
elif sys.version_info >= (2, 7):
    from HTMLParser import HTMLParser
    from urllib2 import HTTPError, urlopen, quote
    from urllib import urlencode
    def u(string):
        return string.encode("utf-8")
else:
    print("Le versioni di Python supportate sono:")
    print(" - 2.7")
    print(" - 3.3 (e superiori)")
    sys.exit(1)

import json
import os
import socket
import time

BASE = "http://80.16.223.45/src/default.aspx?TipoPagina=OSPEDALI&Centrale="

STAZIONI = {
    "Imperia":"IM",
    "Savona":"SV",
    "Genova":"GE",
    "Lavagna":"GE",
    "La Spezia":"SP",
}

# Configurazione dipendente dal sito
COLONNE = (
    "ID missione",
    "ID mezzo",
    "Postazione",
    "Codice effettivo",
    "Località",
    "Indirizzo",
    "Codice soccorso",
    "Ospedale di destinazione",
    "ASL di destinazione",
)
BANDIERE = {
    "flgnc_24.gif":["blue", "phone"],
    "flag-white-24x24.png":["purple", "ambulance"],
    "flag-green-24x24.png":["green", "ambulance"],
    "flag-yellow-24x24.png":["orange", "ambulance"],
    "flag-red-24x24.png":["red", "ambulance"],
}

# http://www.118er.it/parma/internet/documenti/Valori%20NSIS%20per%20operatori%20del%20soccorso.pdf
LUOGHI = {
    "S":"strada",
    "P":"luogo pubblico",
    "Y":"impianto sportivo",
    "K":"casa",
    "L":"impianto lavorativo",
    "Q":"scuola",
    "Z":"non definito",
}
PATOLOGIE = {
    "C01":"traumatica",
    "C02":"cardiocircolatoria",
    "C03":"respiratoria",
    "C04":"neurologica",
    "C05":"psichiatrica",
    "C06":"neoplastica",
    "C07":"intossicazione",
    "C08":"metabolica",
    "C09":"gastroenterologica",
    "C10":"urologica",
    "C11":"oculistica",
    "C12":"otorinolaringoiatrica",
    "C13":"dermatologica",
    "C14":"ostetrico-ginecologica",
    "C15":"inteffiva",
    "C19":"altra patologia",
    "C20":"patologia non identificata",
}

BING = "http://dev.virtualearth.net/REST/v1/Locations?"

def cacheCheck(request):
    if cache:
        for feature in cache["features"]:
            if feature["properties"]["request"] == request:
                return feature
    return False

def getAddress(details):
    details.extend([
        ["countryRegion", "Italy"],
        ["adminDistrict", "Lig."],
        ["maxResults", 1],
    ])
    place = dict(details)
    place["key"] = conf.APIKEY
    authorized = BING + urlencode(place)
    request = "|".join([str(v) for k, v in details])
    feature = cacheCheck(request)
    if feature:
        address = feature["properties"]["address"]
        coordinates = map(float, feature["geometry"]["coordinates"])
    else:
        response = urlopen(authorized).read().decode("utf-8")
        result = json.loads(response)
        partial = result["resourceSets"][0]
        if partial["estimatedTotal"] == 0:
            if "addressLine" in place.keys():
                for index, (key, value) in enumerate(details):
                    if key == "addressLine":
                        del details[index]
                return getAddress(details)
            print("[!] Indirizzo non trovato")
            print(place)
            print(request)
            sys.exit(1)
        resource = partial["resources"][0]
        address = resource["address"]["formattedAddress"]
        coordinates = resource["geocodePoints"][0]["coordinates"]
    return request, address, coordinates

class ProntoSoccorsoParser(HTMLParser):
    def __init__(self, district, *args, **kwargs):
        HTMLParser.__init__(self, *args, **kwargs)
        self.district = district
        self.table = 0
        self.tr = 0
        self.td = 0
        self.info = []
        self.row = {}
    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table += 1
        elif self.table == 2 and tag == "tr":
            if self.tr >= 2: # Più sicuro che aspettare </tr>
                self.flush()
            self.tr += 1
        elif self.tr >= 2 and tag == "td":
            self.td += 1
        elif self.tr >= 2 and self.td == 4 and tag == "img":
            path = dict(attrs)["src"]
            image = path.split("/")[-1]
            self.row["Colore"], self.row["Icona"] = BANDIERE[image]
    def handle_endtag(self, tag):
        if tag == "table":
            if self.table == 2 and self.row:
                self.flush()
            self.table -= 1
    def handle_data(self, data):
        if self.table == 2 and self.tr >= 2:
            if self.td >= 1 and self.td != 4:
                code = data.strip()
                self.row[COLONNE[self.td-1]] = code
                if self.td == 7 and 4 <= len(code) <= 5:
                    if len(code) == 5:
                        self.row["Luogo"] = LUOGHI[code[0]]
                    self.row["Patologia"] = PATOLOGIE[code[-4:-1]]
                    self.row["Codice supposto"] = code[-1]
    def flush(self):
        if "Indirizzo" in self.row.keys():
            indirizzo = self.row["Indirizzo"]
        else:
            indirizzo = ""
        request, place, coordinates = getAddress([
            ["adminDistrict2", STAZIONI[self.district]],
            ["addressLine", indirizzo],
            ["locality", self.row["Località"]],
        ])
        self.row["Request"] = request
        if place and coordinates:
            lat, lng = coordinates
            self.row["Posizione completa"] = place
            self.row["Latitudine"] = lat
            self.row["Longitudine"] = lng
        self.info.append(self.row)
        self.row = {}
        self.td = 0

def clean(html):
    return html.replace("<style=", "<div style=")

def getData(station):
    try:
        request = urlopen(BASE+station.replace(" ", ""), timeout=30)
    except (HTTPError, socket.timeout) as e:
        sys.exit(1)
    response = request.read()
    parser = ProntoSoccorsoParser(station)
    parser.feed(clean(response.decode("utf-8")))
    return parser.info

def getAll():
    info = {}
    for station, district in STAZIONI.items():
        result = getData(station)
        if result:
            info[station] = result
    return info

def geometry(data):
    return {
        "type":"Point",
        "coordinates":["%.4f" % data["Longitudine"], "%.4f" % data["Latitudine"]],
    }

def properties(data):
    descrizione = [
        "<b>%(Codice soccorso)s</b>",
        "Indirizzo: %(Posizione completa)s",
        "Postazione: %(Postazione)s", 
        "Trasportato a: %(Ospedale di destinazione)s",
    ]
    if "Luogo" in data.keys():
        descrizione.insert(1, "Luogo: %(Luogo)s")
    if "Patologia" in data.keys():
        descrizione.insert(1, "Patologia: %(Patologia)s")
    return {
        "icon":data["Icona"],
        "color":data["Colore"],
        "title":"<br />".join(descrizione) % data,
        "request":data["Request"],
        "address":data["Posizione completa"],
    }

def features(info):
    tmp = []
    for station, datas in info.items():
        for data in datas:
            if "Posizione completa" in data.keys():
                tmp.append({
                    "type":"Feature",
                    "geometry":geometry(data),
                    "properties":properties(data),
                })
    return tmp

if __name__ == "__main__":
    if os.path.isfile(conf.OUTPUT):
        with open(conf.OUTPUT, "r") as textfile:
            cache = json.loads(textfile.read().lstrip(conf.PREFIX))
    else:
        cache = {}
    info = getAll()
    geojson = {
        "type":"FeatureCollection",
        "features":features(info),
    }
    with open(conf.OUTPUT, "w") as textfile:
        textfile.write(conf.PREFIX)
        textfile.write(json.dumps(geojson))
