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

import collections
import json
import os
import shelve
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
    "flgnc_24.gif":None,
    "flag-white-24x24.png":"bianco",
    "flag-green-24x24.png":"verde",
    "flag-yellow-24x24.png":"giallo",
    "flag-red-24x24.png":"rosso",
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

CACHED = 256

BING = "http://dev.virtualearth.net/REST/v1/Locations?"

def getAddress(place):
    place.update({
        "key":conf.APIKEY,
        "countryRegion":"Italy",
        "adminDistrict":"Lig.",
        "maxResults":1,
    })
    request = BING + urlencode(place)
    if request in cache.keys():
        address, coordinates = cache[request]
    else:
        response = urlopen(request).read().decode("utf-8")
        result = json.loads(response)
        partial = result["resourceSets"][0]
        if partial["estimatedTotal"] == 0:
            cache[request] = [None, None]
            return [None, None]
        resource = partial["resources"][0]
        address = resource["address"]["formattedAddress"]
        coordinates = resource["geocodePoints"][0]["coordinates"]
        cache[request] = [address, coordinates]
    return address, coordinates

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
            if image == "flgnc_24.gif": # Ugly flag
                flag = "../img/flag-blue-24x24.png" # To be changed
            else:
                flag = "../img/"+image
            self.row["Bandiera"] = "http://80.16.223.45/src/"+flag
            self.row[COLONNE[3]] = BANDIERE[image]
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
        place, coordinates = getAddress({
            "adminDistrict2":STAZIONI[self.district],
            "addressLine":indirizzo,
            "locality":self.row["Località"],
        })
        if place:
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
        "icon":data["Bandiera"],
        "title":"<br />".join(descrizione) % data,
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

def main():
    info = getAll()
    geojson = {
        "type":"FeatureCollection",
        "features":features(info),
    }
    with open(conf.OUTPUT, "w") as textfile:
        textfile.write("data = "+json.dumps(geojson))
    return info

if __name__ == "__main__":
    cache = shelve.open(conf.CACHE)
    if len(cache) > CACHED:
        for key in cache.keys():
            del cache[key]
    main()
    cache.close()
