#!/usr/bin/env python3
"""
Mes Papiers - copie automatique du cloud (Supabase) vers le PC
---------------------------------------------------------------
Recopie tous tes documents dans un dossier lisible :
    D:\\GGI\\MESPAPIERS\\<Catégorie>\\<Année>\\<date> - <intitulé>.pdf

    python copie-pc.py             -> copie en boucle toutes les 10 minutes
    python copie-pc.py --une-fois  -> une seule copie puis s'arrête (tâche planifiée)

Au premier lancement, il demande ton e-mail et ton mot de passe Mes Papiers
et les garde dans copie-pc.ini (à côté de ce fichier).
Aucune installation : uniquement Python 3.8+.
"""
import configparser, getpass, json, os, re, shutil, sys, time, traceback
import urllib.request, urllib.error
from pathlib import Path
from urllib.parse import quote

# --- projet Supabase de Gérard (la clé « anon » est publique par nature) ---
SUPABASE_URL = "https://favbetrbvzxpvodsiimt.supabase.co"
SUPABASE_KEY = "sb_publishable_CVLnuDvOXmGz1TyyTCuBiQ__JUw7g0w"

HERE = Path(__file__).resolve().parent
INI = HERE / "copie-pc.ini"
LOGF = HERE / "copie-pc.log"
DEFAULT_ROOT = r"D:\GGI\MESPAPIERS" if os.name == "nt" else str(Path.home() / "MesPapiers")
INTERVALLE = 600  # secondes

CATS = {
    "banque": "Banque & comptes", "factures": "Factures", "assurances": "Assurances",
    "impots": "Impôts", "sante": "Santé & mutuelle", "logement": "Logement",
    "vehicule": "Véhicules", "garanties": "Achats & garanties", "abonnements": "Abonnements",
    "travail": "Travail & retraite", "identite": "Identité & famille", "divers": "Divers",
}


def log(msg):
    line = time.strftime("%d/%m %H:%M:%S  ") + msg
    try:
        print(line)
    except Exception:
        pass
    try:
        with open(LOGF, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if LOGF.stat().st_size > 1_000_000:
            LOGF.replace(LOGF.with_suffix(".old.log"))
    except Exception:
        pass


# ------------------------------------------------------------------ réglages
def config():
    cp = configparser.ConfigParser()
    if INI.exists():
        cp.read(INI, encoding="utf-8")
    if "mespapiers" not in cp:
        cp["mespapiers"] = {}
    c = cp["mespapiers"]
    changed = False
    if not c.get("url") and SUPABASE_URL:
        c["url"] = SUPABASE_URL; changed = True
    if not c.get("cle") and SUPABASE_KEY:
        c["cle"] = SUPABASE_KEY; changed = True
    if not c.get("dossier"):
        c["dossier"] = DEFAULT_ROOT; changed = True
    if not sys.stdin or not sys.stdin.isatty():
        if not all(c.get(k) for k in ("url", "cle", "email", "mot_de_passe")):
            log("Réglages incomplets : lance une fois copie-pc.py à la main (double-clic sur le .bat).")
            sys.exit(1)
    else:
        print("=" * 60)
        print(" Mes Papiers - copie automatique vers le PC")
        print("=" * 60)
        if not c.get("url"):
            c["url"] = input("Adresse du projet Supabase (https://....supabase.co) : ").strip(); changed = True
        if not c.get("cle"):
            c["cle"] = input("Clé publique (anon / publishable) : ").strip(); changed = True
        if not c.get("email"):
            c["email"] = input("Ton e-mail Mes Papiers : ").strip(); changed = True
        if not c.get("mot_de_passe"):
            c["mot_de_passe"] = getpass.getpass("Ton mot de passe Mes Papiers (ne s'affiche pas) : "); changed = True
    if changed:
        with open(INI, "w", encoding="utf-8") as f:
            cp.write(f)
    return c


# ------------------------------------------------------------------ Supabase
class SB:
    def __init__(self, c):
        self.url = c["url"].rstrip("/")
        self.key = c["cle"]
        self.email, self.pwd = c["email"], c["mot_de_passe"]
        self.token = self.uid = None

    def req(self, method, path, body=None, headers=None, raw=False):
        h = {"apikey": self.key}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        if body is not None and not isinstance(body, bytes):
            body = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        r = urllib.request.Request(self.url + path, data=body, method=method, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=120) as resp:
                data = resp.read()
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")
            try:
                j = json.loads(txt)
                txt = j.get("msg") or j.get("message") or j.get("error_description") or txt
            except Exception:
                pass
            raise RuntimeError(f"{e.code} {txt}")
        return data if raw else (json.loads(data) if data else None)

    def login(self):
        j = self.req("POST", "/auth/v1/token?grant_type=password", {"email": self.email, "password": self.pwd})
        self.token, self.uid = j["access_token"], j["user"]["id"]

    def rows(self):
        return self.req("GET", "/rest/v1/docs?select=id,data,modifie,supprime&limit=50000")

    def file(self, did, fid):
        p = "/".join(quote(x, safe="") for x in (self.uid, did, fid))
        return self.req("GET", "/storage/v1/object/authenticated/papiers/" + p, raw=True)


# ------------------------------------------------------------------ rangement
def clean(s, maxlen=80):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(s or "")).strip()
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:maxlen].strip(" .") or "Sans titre"


def target(root, doc, f, idx, n):
    cat = clean(CATS.get(doc.get("categorie"), doc.get("categorie") or "Divers"))
    dos = doc.get("dossier") or "perso"
    if dos != "perso":   # autres dossiers (SCI, belle-maman...) : dans leur propre sous-dossier
        root = root / clean(doc.get("dossierNom") or dos)
    date = doc.get("date") or ""
    year = date[:4] if re.match(r"^\d{4}", date) else "Sans date"
    base = clean((date + " - " if date else "") + (doc.get("titre") or ""))
    ext = Path(f.get("nom") or "").suffix.lower() or (".pdf" if "pdf" in (f.get("type") or "") else ".jpg")
    if n > 1:
        base += f" ({idx + 1})"
    return root / cat / year / (base + ext)


def unique(path, current=None):
    if current is not None and path == current:
        return path
    if not path.exists():
        return path
    k = 2
    while True:
        p = path.with_name(f"{path.stem} ({k}){path.suffix}")
        if not p.exists() or (current is not None and p == current):
            return p
        k += 1


def to_trash(root, rel):
    src = root / rel
    if src.exists():
        (root / "_Corbeille").mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(unique(root / "_Corbeille" / src.name)))


def load_index(root):
    f = root / ".mes-papiers.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            shutil.copy(f, f.with_suffix(".json.abime-%d" % int(time.time())))
    return {"docs": {}, "supprimes": {}}


def save_index(root, data):
    f = root / ".mes-papiers.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if os.name == "nt" and f.exists():
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(f), 0)
        except Exception:
            pass
    os.replace(tmp, f)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(f), 2)  # caché
        except Exception:
            pass


def copie(c):
    root = Path(c["dossier"])
    root.mkdir(parents=True, exist_ok=True)
    sb = SB(c)
    sb.login()
    rows = sb.rows()
    for r in [r for r in rows if r.get("id") == "__cats__"]:   # catégories personnalisées (Mes Papiers)
        if not r.get("supprime"):
            for c in (r.get("data") or {}).get("list", []):
                if c.get("id") and c.get("nom"):
                    CATS[c["id"]] = c["nom"]
    rows = [r for r in rows if not str(r.get("id", "")).startswith("__")]   # catégories, notes, coffre
    idx = load_index(root)
    nouveaux = maj = suppr = 0
    for r in rows:
        did = r["id"]
        if r.get("supprime"):
            old = idx["docs"].pop(did, None)
            if old:
                for f in old.get("fichiers", []):
                    if f.get("chemin"):
                        to_trash(root, f["chemin"])
                idx["supprimes"][did] = r.get("modifie")
                suppr += 1
                log(f"🗑  {old.get('titre')}  -> _Corbeille")
            continue
        doc = dict(r.get("data") or {}, id=did)
        old = idx["docs"].get(did)
        files_ok = old and all(f.get("chemin") and (root / f["chemin"]).exists() for f in old.get("fichiers", []))
        if old and old.get("modifie") == doc.get("modifie") and files_ok \
                and {f["id"] for f in old.get("fichiers", [])} == {f["id"] for f in doc.get("fichiers", [])}:
            continue
        have = {f["id"]: f for f in (old or {}).get("fichiers", [])}
        keep_ids = {f["id"] for f in doc.get("fichiers", [])}
        for fid, f in have.items():
            if fid not in keep_ids and f.get("chemin"):
                to_trash(root, f["chemin"])
        out = []
        n = len(doc.get("fichiers", []))
        for i, f in enumerate(doc.get("fichiers", [])):
            f = {k: f.get(k) for k in ("id", "nom", "type", "taille")}
            prev = have.get(f["id"], {})
            cur = root / prev["chemin"] if prev.get("chemin") else None
            if cur is not None and cur.exists():
                dest = unique(target(root, doc, f, i, n), cur)
                if dest != cur:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(cur), str(dest))
            else:
                dest = unique(target(root, doc, f, i, n))
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(sb.file(did, f["id"]))
            f["chemin"] = dest.relative_to(root).as_posix()
            out.append(f)
        doc["fichiers"] = out
        idx["docs"][did] = doc
        idx["supprimes"].pop(did, None)
        save_index(root, idx)
        if old:
            maj += 1; log(f"✏  {doc.get('titre')}")
        else:
            nouveaux += 1; log(f"📄 {doc.get('titre')}  -> {out[0]['chemin'] if out else '(sans fichier)'}")
    save_index(root, idx)
    log(f"Copie terminée : {nouveaux} nouveau(x), {maj} modifié(s), {suppr} supprimé(s) · {len(idx['docs'])} document(s) sur le PC")


def main():
    c = config()
    once = "--une-fois" in sys.argv
    while True:
        try:
            copie(c)
        except Exception as e:
            msg = str(e)
            if "Invalid login" in msg or "invalid_credentials" in msg:
                log("❌ E-mail ou mot de passe refusé. Supprime copie-pc.ini et relance pour les ressaisir.")
            elif isinstance(e, (urllib.error.URLError, TimeoutError, OSError)) and not isinstance(e, RuntimeError):
                log(f"⏳ Pas de connexion internet ({e}). Nouvel essai plus tard.")
            else:
                log("❌ Erreur : " + msg)
                with open(LOGF, "a", encoding="utf-8") as f:
                    traceback.print_exc(file=f)
        if once:
            break
        time.sleep(INTERVALLE)


if __name__ == "__main__":
    main()
