"""Controlled vocabulary: one hierarchy drives the prompt, validation,
catalogue normalisation and link scoring.

Shape tuple: id, label, AAT-style plural label, Greek, parent, function group,
grounding (ancient | conventional | modern), scope note, regex.
AAT numeric identifiers are NOT included; resolve them against the Getty
vocabulary service before publishing anything that cites them.
"""
import re

FN = [
 ("drinking","Drinking vessels"),("mixing","Mixing and cooling vessels"),("storage","Storage and transport vessels"),
 ("water","Water vessels"),("pouring","Pouring vessels"),("oil","Oil and perfume vessels"),
 ("toilet","Toilet and trinket containers"),("ritual","Ritual, wedding and funerary vessels"),
 ("serving","Serving vessels"),("other","Other forms"),
]
# id, label, AAT-style plural label, greek, parent, fn, grounding, scope note, regex
S = [
 # drinking
 ("eye-cup","eye-cup","eye cups","","kylix","drinking","modern","Kylix with large apotropaic eyes on the exterior.",r"eye[- ]cup"),
 ("lip-cup","lip-cup","lip cups","","kylix","drinking","modern","Little-Master cup with offset lip carrying the figure.",r"lip[- ]cup"),
 ("band-cup","band-cup","band cups","","kylix","drinking","modern","Little-Master cup with figures in the handle zone band.",r"band[- ]cup"),
 ("little-master-cup","Little-Master cup","Little-Master cups","","kylix","drinking","modern","Small-figured black-figure cup, mid sixth century BCE.",r"little[- ]master"),
 ("siana-cup","Siana cup","Siana cups","","kylix","drinking","modern","Early black-figure cup with tall offset lip and conical foot.",r"siana"),
 ("komast-cup","komast cup","komast cups","","kylix","drinking","modern","Earliest Attic black-figure cup type, named for its revellers.",r"komast"),
 ("stemless-cup","stemless cup","stemless cups","","kylix","drinking","modern","Kylix bowl set directly on a ring foot.",r"stemless"),
 ("cup-skyphos","cup-skyphos","cup-skyphoi","","skyphos","drinking","modern","Hybrid between the kylix bowl and skyphos body.",r"cup[- ]skyphos|skyphoid"),
 ("kotyle","kotyle","kotylai","κοτύλη","skyphos","drinking","conventional","Deep cup with two horizontal handles; used for the Corinthian form.",r"kotyl"),
 ("skyphos","skyphos","skyphoi","σκύφος","","drinking","ancient","Deep drinking cup with two handles at the rim and a low foot.",r"sk[yu]pho"),
 ("kantharos","kantharos","kantharoi","κάνθαρος","","drinking","ancient","Deep cup with two high vertical handles; attribute of Dionysos.",r"kanthar|canthar"),
 ("kyathos","kyathos","kyathoi","κύαθος","","drinking","conventional","Dipper cup with one tall looped handle.",r"kyath|cyath"),
 ("mastos","mastos","mastoi","μαστός","","drinking","conventional","Breast-shaped cup.",r"masto"),
 ("rhyton","rhyton","rhyta","ῥυτόν","","drinking","ancient","Drinking or libation horn, often with an animal-head terminal.",r"rhyt"),
 ("mug","mug","mugs","","","drinking","modern","One-handled drinking vessel; includes tankards and beakers.",r"\bmugs?\b|tankard|beaker"),
 ("kylix","kylix","kylikes","κύλιξ","","drinking","ancient","Shallow stemmed cup with two horizontal handles; the standard symposium cup.",r"kylix|kylik|cylix"),
 # mixing
 ("column-krater","column-krater","column kraters","","krater","mixing","modern","Krater with columnar handles supporting a flat rim plate.",r"column[- ]krater"),
 ("calyx-krater","calyx-krater","calyx kraters","","krater","mixing","modern","Krater with flaring body and low upturned handles, like a flower calyx.",r"cal[yi]x[- ]krater"),
 ("volute-krater","volute-krater","volute kraters","","krater","mixing","modern","Krater whose handles rise in scrolls above the rim.",r"volute[- ]krater"),
 ("bell-krater","bell-krater","bell kraters","","krater","mixing","modern","Bell-shaped krater with small horizontal handles set high.",r"bell[- ]krater"),
 ("krater","krater","kraters","κρατήρ","","mixing","ancient","Wide-mouthed bowl for mixing wine and water at the symposium.",r"krater|crater"),
 ("dinos","dinos (lebes)","dinoi","λέβης","","mixing","conventional","Round-bottomed mixing bowl set on a stand; the ancient name was lebes.",r"\bdino|\blebes(?! gam)"),
 ("stamnos","stamnos","stamnoi","στάμνος","","mixing","conventional","Broad-shouldered jar with short neck and two horizontal handles.",r"stamno"),
 ("psykter","psykter","psykters","ψυκτήρ","","mixing","ancient","Mushroom-shaped wine cooler floated inside a krater.",r"psykter"),
 # storage
 ("panathenaic-amphora","Panathenaic prize amphora","Panathenaic amphorae","","neck-amphora","storage","conventional","Prize vessel for the Panathenaic games, filled with sacred oil.",r"panathenaic"),
 ("nolan-amphora","Nolan amphora","Nolan amphorae","","neck-amphora","storage","modern","Small slender red-figure neck-amphora, named for finds at Nola.",r"nolan"),
 ("tyrrhenian-amphora","Tyrrhenian amphora","Tyrrhenian amphorae","","neck-amphora","storage","modern","Ovoid Attic black-figure neck-amphora made for the Etruscan market.",r"tyrrhenian"),
 ("nikosthenic-amphora","Nikosthenic amphora","Nikosthenic amphorae","","neck-amphora","storage","modern","Angular amphora with broad strap handles from the workshop of Nikosthenes.",r"nikosthenic|nicosthenic"),
 ("pointed-amphora","pointed amphora","pointed amphorae","","neck-amphora","storage","modern","Amphora tapering to a point, needing a stand.",r"pointed amphora"),
 ("neck-amphora","neck-amphora","neck amphorae","","amphora","storage","modern","Amphora whose neck meets the body at a sharp angle.",r"neck[- ](handled )?amphora"),
 ("belly-amphora","belly amphora (one-piece)","belly amphorae","","amphora","storage","modern","Amphora with a continuous curve from neck to body; types A, B and C.",r"belly|panel[- ]amphora|one[- ]piece|amphora,? type [abc]"),
 ("amphoriskos","amphoriskos","amphoriskoi","ἀμφορίσκος","amphora","storage","ancient","Miniature amphora, usually for perfumed oil.",r"amphorisk"),
 ("amphora","amphora","amphorae","ἀμφορεύς","","storage","ancient","Two-handled jar for storing and carrying wine, oil and dry goods.",r"amphora"),
 ("pelike","pelike","pelikai","πελίκη","","storage","conventional","Amphora variant with sagging belly and wide mouth.",r"pelik"),
 ("stirrup-jar","stirrup jar","stirrup jars","","","storage","modern","Closed Aegean Bronze Age jar with false neck and stirrup handles.",r"stirrup"),
 ("pithos","pithos","pithoi","πίθος","","storage","ancient","Large storage jar.",r"pitho"),
 ("jar","jar","jars","","","storage","modern","Generic closed storage form with no more specific type recorded.",r"\bjars?\b"),
 # water
 ("kalpis","kalpis","kalpides","κάλπις","hydria","water","conventional","Hydria with a continuous curve from neck to shoulder.",r"kalpi"),
 ("hydria","hydria","hydriai","ὑδρία","","water","ancient","Water jar with two horizontal handles for lifting and one vertical for pouring.",r"hydria"),
 # pouring
 ("chous","chous","choes","χοῦς","oinochoe","pouring","ancient","Squat trefoil-mouthed jug tied to the Anthesteria festival.",r"\bchou|\bchoes"),
 ("olpe","olpe","olpai","ὄλπη","oinochoe","pouring","conventional","Slender jug with sagging profile and round or trefoil mouth.",r"\bolp"),
 ("oinochoe","oinochoe","oinochoai","οἰνοχόη","","pouring","ancient","Wine jug with a single vertical handle.",r"oinocho|oenocho"),
 ("epichysis","epichysis","epichyseis","ἐπίχυσις","","pouring","conventional","South Italian jug with spool-shaped body and long spout.",r"epichys"),
 ("askos","askos","askoi","ἀσκός","","pouring","conventional","Low closed vessel with a spout and arched handle, shaped like a wineskin.",r"\basko"),
 ("jug","jug","jugs","","","pouring","modern","Generic one-handled pouring vessel, including pitchers and juglets.",r"\bjug|pitcher"),
 # oil
 ("squat-lekythos","squat lekythos","squat lekythoi","","lekythos","oil","modern","Lekythos with rounded body on a broad flat base.",r"squat lek"),
 ("lekythos","lekythos","lekythoi","λήκυθος","","oil","ancient","Narrow-necked oil flask with one handle; the standard Attic funerary offering.",r"lek[yi]th|lecyth"),
 ("aryballos","aryballos","aryballoi","ἀρύβαλλος","","oil","conventional","Small globular oil flask carried by athletes.",r"aryball"),
 ("alabastron","alabastron","alabastra","ἀλάβαστρον","","oil","ancient","Elongated handleless perfume flask with a flat disc mouth.",r"alabastr"),
 ("lydion","lydion","lydia","λύδιον","","oil","conventional","Small footed jar for perfumed ointment, of Lydian origin.",r"lydion"),
 ("exaleiptron","exaleiptron","exaleiptra","ἐξάλειπτρον","","oil","conventional","Low perfume vessel with incurved rim; also called kothon or plemochoe.",r"exaleiptr|kothon|plemocho"),
 ("unguentarium","unguentarium","unguentaria","","","oil","modern","Small Hellenistic and Roman bottle for oils and perfumes.",r"unguentar|balsamar"),
 # toilet
 ("pyxis","pyxis","pyxides","πυξίς","","toilet","conventional","Lidded box for cosmetics or jewellery.",r"pyxi"),
 ("lekanis","lekanis","lekanides","λεκανίς","","toilet","conventional","Low lidded bowl with two horizontal handles.",r"lekani"),
 # ritual
 ("loutrophoros","loutrophoros","loutrophoroi","λουτροφόρος","","ritual","ancient","Tall-necked vessel for the bridal bath; grave marker for the unmarried.",r"loutrophor"),
 ("lebes-gamikos","lebes gamikos","lebetes gamikoi","λέβης γαμικός","","ritual","conventional","Wedding bowl on a tall stand with upright handles.",r"lebes gam"),
 ("phiale","phiale","phialai","φιάλη","","ritual","ancient","Shallow handleless libation bowl, often with a central boss.",r"phial|patera"),
 ("kernos","kernos","kernoi","κέρνος","","ritual","ancient","Ring or stand carrying several small offering cups.",r"kerno"),
 ("epinetron","epinetron","epinetra","ἐπίνητρον","","ritual","ancient","Knee guard used in preparing wool; a wedding gift.",r"epinetr|\bonos\b"),
 # serving
 ("fish-plate","fish-plate","fish plates","","plate","serving","modern","Plate with a central depression, decorated with fish.",r"fish[- ]?plate"),
 ("plate","plate","plates","πίναξ","","serving","conventional","Flat open serving vessel.",r"\bplates?\b"),
 ("bowl","bowl","bowls","","","serving","modern","Generic open form with no more specific type recorded.",r"\bbowls?\b"),
 ("dish","dish","dishes","","","serving","modern","Generic shallow open form.",r"\bdish"),
 # other
 ("pinax","pinax (plaque)","pinakes","πίναξ","","other","ancient","Painted votive or funerary plaque.",r"pinax|plaque"),
 ("figure-vase","figure vase","figure vases","","","other","modern","Mould-made vessel in the shape of a head, animal or figure.",r"plastic|head vase|figure vase|janiform|[- ]shaped vase|hedgehog"),
 ("nestoris","nestoris","nestorides","","","other","modern","South Italian jar with high handles carrying discs.",r"nestori"),
 ("situla","situla","situlae","","","other","modern","Bucket-shaped vessel.",r"situla"),
 ("kalathos","kalathos","kalathoi","κάλαθος","","other","ancient","Basket-shaped vessel.",r"kalatho"),
 ("flask","flask or bottle","flasks","","","other","modern","Generic narrow-necked closed form.",r"flask|bottle"),
 ("lid","lid","lids","","","other","modern","Detached lid.",r"^lid\b"),
 ("stand","stand","stands","","","other","modern","Detached stand.",r"^stand\b"),
]
T = [
 ("bilingual","bilingual","Black-figure on one side, red-figure on the other.",r"bilingual"),
 ("six","Six's technique","Added colour over black glaze with incised detail.",r"six'?s"),
 ("white-ground","white-ground","Figures on a white slip.",r"white[- ]ground"),
 ("black-figure","black-figure","Black silhouettes with incised detail on the clay ground.",r"black[- ]figure"),
 ("red-figure","red-figure","Reserved figures against a black-glazed ground.",r"red[- ]figure"),
 ("black-glaze","black-glaze","Plain black gloss without figures.",r"black[- ]gla"),
 ("gnathian","Gnathian","Polychrome paint over black gloss, South Italian.",r"gnath"),
 ("protogeometric","Protogeometric","Compass-drawn circles and bands.",r"protogeometric"),
 ("geometric","Geometric","Rectilinear patterns and schematic figures.",r"geometric"),
 ("wild-goat","Wild Goat style","East Greek animal friezes.",r"wild goat|fikellura"),
 ("bucchero","bucchero","Etruscan black reduction-fired ware.",r"bucchero"),
 ("red-slip","red slip (terra sigillata)","Glossy red-slipped Roman tableware.",r"red slip|sigillata|arretine"),
 ("lead-glazed","lead-glazed","Vitreous lead glaze, Hellenistic and Roman.",r"lead[- ]glaz"),
 ("relief","relief-decorated","Mould-made or applied relief.",r"relief"),
]
F = [
 ("attic","Attic","Athens and Attica",r"\battic|athenian|protoattic"),
 ("corinthian","Corinthian","Corinth",r"corinthian"),
 ("boeotian","Boeotian","Boeotia",r"boeotian|kabiric"),
 ("laconian","Laconian","Sparta and Laconia",r"laconian|lakonian"),
 ("euboean","Euboean and Chalcidian","Euboea and its western colonies",r"chalcidian|euboean"),
 ("east-greek","East Greek","Ionia, Rhodes and the eastern Aegean",r"east greek|ionian|rhodian|milesian|fikellura|chian|clazomen"),
 ("cycladic","Cycladic","Cyclades",r"cycladic"),
 ("apulian","Apulian","South Italian, Apulia",r"apulian|gnath"),
 ("lucanian","Lucanian","South Italian, Lucania",r"lucanian"),
 ("paestan","Paestan","South Italian, Paestum",r"paestan"),
 ("campanian","Campanian","South Italian, Campania",r"campanian"),
 ("sicilian","Sicilian","Sicily",r"sicilian|centuripe"),
 ("south-italian","South Italian","South Italy, workshop unspecified",r"south italian"),
 ("etruscan","Etruscan","Etruria",r"etrusc|caeretan|faliscan|pontic|bucchero"),
 ("mycenaean","Mycenaean","Late Bronze Age Greek mainland",r"mycenaean|helladic|minyan"),
 ("minoan","Minoan","Bronze Age Crete",r"minoan|marine style"),
 ("cypriot","Cypriot","Cyprus",r"cyprio|base ring|black on red"),
 ("lydian","Lydian","Lydia",r"lydian"),
 ("roman","Roman","Roman world",r"roman|north african|thin-walled"),
]
P = [("bronze-age","Bronze Age",-3000,-1050,r"bronze age|helladic|minoan|mycenaean|cypro-?bronze"),
     ("geometric","Protogeometric and Geometric",-1050,-700,r"geometric|iron age"),
     ("orientalizing","Orientalizing",-700,-600,r"orientali[sz]ing|early archaic|protoattic|protocorinthian"),
     ("archaic","Archaic",-600,-480,r"archaic"),
     ("classical","Classical",-480,-323,r"classical"),
     ("hellenistic","Hellenistic",-323,-31,r"hellenistic"),
     ("roman","Roman Imperial",-31,476,r"roman|imperial")]

GENERIC={"jar","jug","bowl","dish","mug","flask","plate","lid","stand"}
FALLBACK=[("kylix",r"\bcups?\b")]

SHAPES = {s[0]: dict(id=s[0], label=s[1], aat=s[2], greek=s[3], parent=s[4], fn=s[5],
                     grounding=s[6], note=s[7], re=re.compile(s[8], re.I)) for s in S}
TECHNIQUES = {t[0]: dict(id=t[0], label=t[1], note=t[2], re=re.compile(t[3], re.I)) for t in T}
FABRICS = {f[0]: dict(id=f[0], label=f[1], note=f[2], re=re.compile(f[3], re.I)) for f in F}
PERIODS = {p[0]: dict(id=p[0], label=p[1], start=p[2], end=p[3], re=re.compile(p[4], re.I)) for p in P}
FN_LABEL = dict(FN)
_FALLBACK = [(i, re.compile(r, re.I)) for i, r in FALLBACK]
SOUTH_ITALIAN = {"apulian", "lucanian", "paestan", "campanian", "sicilian", "south-italian"}


def match_shape(text):
    """Specific terms first, then the bare word 'cup' (= kylix), then generics."""
    if not text:
        return None
    for s in SHAPES.values():
        if s["id"] not in GENERIC and s["re"].search(text):
            return s["id"]
    for sid, rx in _FALLBACK:
        if rx.search(text):
            return sid
    for s in SHAPES.values():
        if s["id"] in GENERIC and s["re"].search(text):
            return s["id"]
    return None


def first_hit(table, text):
    if not text:
        return None
    for x in table.values():
        if x["re"].search(text):
            return x["id"]
    return None


def period_of_year(year):
    if year is None:
        return None
    for p in PERIODS.values():
        if p["start"] <= year < p["end"]:
            return p["id"]
    return None


def ancestors(sid):
    out, s = [], SHAPES.get(sid)
    while s and s["parent"]:
        out.append(s["parent"])
        s = SHAPES.get(s["parent"])
    return out


def depth(sid):
    """2 = shape, 3 = variant, 4 = sub-variant; 0 if not in the vocabulary."""
    return len(ancestors(sid)) + 2 if sid in SHAPES else 0


def shape_relation(a, b):
    """Relation of candidate a to reference b, with a similarity in [0, 1]."""
    if not a or not b or a not in SHAPES or b not in SHAPES:
        return "none", 0.0
    if a == b:
        return "exact", 1.0
    if b in ancestors(a):
        return "more specific", 0.7
    if a in ancestors(b):
        return "less specific", 0.7
    if SHAPES[a]["parent"] and SHAPES[a]["parent"] == SHAPES[b]["parent"]:
        return "sibling type", 0.5
    if (ancestors(a) or [a])[-1] == (ancestors(b) or [b])[-1]:
        return "same family", 0.5
    if SHAPES[a]["fn"] == SHAPES[b]["fn"]:
        return "same function group", 0.25
    return "different", 0.0
