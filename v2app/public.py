import json
from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, request, send_from_directory, url_for

from .db import get_db
from .search import search_entries
from .i18n import public_ui

bp = Blueprint("public", __name__)


def language_urls():
    links = {}
    for language in ("ja", "yonaguni", "en", "zh-tw"):
        values = request.args.to_dict()
        values["language"] = language
        links[language] = url_for(request.endpoint, **(request.view_args or {}), **values)
    return links


@bp.get("/")
def index():
    language = request.args.get("language", "ja")
    if language not in ("ja","en","zh-tw","yonaguni"): language = "ja"
    search_type = request.args.get("type", "headword")
    if search_type not in ("headword", "fulltext", "examples", "conjugation"): search_type = "headword"
    match_mode = request.args.get("match", "contains")
    if match_mode not in ("contains", "prefix", "suffix"): match_mode = "contains"
    query = request.args.get("q", "").strip(); results = []
    if query:
        results = search_entries(get_db(), query, "ja" if language=="yonaguni" else language,
                                 search_type, match_mode)
    return render_template("public/index.html", query=query, results=results, language=language,
                           search_type=search_type, match_mode=match_mode,
                           ui=public_ui(language), language_urls=language_urls())


@bp.get("/word/<int:entry_id>")
@bp.get("/word/<int:entry_id>-<slug>")
def entry(entry_id, slug=None):
    db=get_db(); language=request.args.get("language","ja"); display="ja" if language=="yonaguni" else language
    if language not in ("ja","en","zh-tw","yonaguni"):
        language="ja"; display="ja"
    search_query = request.args.get("q", "").strip()
    search_type = request.args.get("type", "headword")
    if search_type not in ("headword", "fulltext", "examples", "conjugation"): search_type = "headword"
    match_mode = request.args.get("match", "contains")
    if match_mode not in ("contains", "prefix", "suffix"): match_mode = "contains"
    back_url = url_for(
        "public.index",
        language=language,
        q=search_query,
        type=search_type,
        match=match_mode,
        _anchor="results",
    ) if search_query else url_for("public.index", language=language)
    row=db.execute("SELECT e.* FROM entries e JOIN entry_workflow w ON w.entry_id=e.id WHERE e.id=? AND w.publication_status='published'",(entry_id,)).fetchone()
    if not row: abort(404)
    meanings=db.execute("SELECT meaning_number,definition FROM meanings WHERE entry_id=? AND language=? AND TRIM(COALESCE(definition,''))!='' ORDER BY meaning_number",(entry_id,display)).fetchall()
    fallback=False
    if not meanings and display!="ja": meanings=db.execute("SELECT meaning_number,definition FROM meanings WHERE entry_id=? AND language='ja' AND TRIM(COALESCE(definition,''))!='' ORDER BY meaning_number",(entry_id,)).fetchall(); fallback=True
    examples=[]
    for ex in db.execute("SELECT ex.* FROM examples ex LEFT JOIN example_state es ON es.example_id=ex.id WHERE ex.entry_id=? AND COALESCE(es.is_archived,0)=0 ORDER BY ex.id",(entry_id,)):
        trans=db.execute("SELECT word_by_word,free_translation FROM example_translations WHERE example_id=? AND language=? ORDER BY id LIMIT 1",(ex["id"],display)).fetchone()
        if not trans and display!="ja": trans=db.execute("SELECT word_by_word,free_translation FROM example_translations WHERE example_id=? AND language='ja' ORDER BY id LIMIT 1",(ex["id"],)).fetchone()
        audio=db.execute("SELECT file_path FROM media_files WHERE example_id=? AND file_type='audio' AND COALESCE(is_archived,0)=0 AND COALESCE(is_pending,0)=0 ORDER BY id DESC LIMIT 1",(ex["id"],)).fetchone()
        examples.append({"sentence":ex["yonaguni_sentence"],"translation":trans,"audio":audio[0] if audio else None})
    source_sections=[]
    for section_row in db.execute("SELECT ss.content_json,s.name,s.abbreviation,s.bibliography,s.url FROM entry_source_sections ss JOIN sources s ON s.id=ss.source_id WHERE ss.entry_id=? ORDER BY ss.sort_order,ss.id",(entry_id,)):
        content=json.loads(section_row["content_json"]); section=dict(section_row)
        section.update(content)
        section_meanings=content.get("meanings",{}).get(display)
        if not section_meanings and display!="ja":
            section_meanings=content.get("meanings",{}).get("ja",[])
            if section_meanings: fallback=True
        section_meanings=section_meanings or []
        section["display_meanings"]=[value for value in section_meanings if value]
        section_examples=[]
        for example in content.get("examples",[]):
            translations=example.get("translations",{}); translation=translations.get(display)
            if not translation and display!="ja": translation=translations.get("ja")
            section_examples.append({"sentence":example.get("yonaguni",""),"translation":translation})
        section["display_examples"]=section_examples
        section["safe_url"] = section["url"] if (section["url"] or "").startswith(("https://", "http://")) else None
        source_sections.append(section)
    media=db.execute("SELECT file_type,file_path,description FROM media_files WHERE entry_id=? AND example_id IS NULL AND COALESCE(is_archived,0)=0 AND COALESCE(is_pending,0)=0",(entry_id,)).fetchall()
    conjugations=db.execute("SELECT form_name,conjugated_form FROM conjugations WHERE entry_id=?",(entry_id,)).fetchall()
    synonyms=db.execute("SELECT synonym FROM synonyms WHERE entry_id=?",(entry_id,)).fetchall()
    has_default_meanings=bool(meanings or synonyms)
    return render_template("public/entry.html",entry=row,meanings=meanings,examples=examples,source_sections=source_sections,has_default_meanings=has_default_meanings,media=media,conjugations=conjugations,synonyms=synonyms,language=language,fallback=fallback,back_url=back_url,ui=public_ui(language),language_urls=language_urls())


@bp.get("/media/<path:filename>")
def media(filename):
    root=Path(current_app.config["MEDIA_ROOT"])
    return send_from_directory(root,filename)


@bp.get("/sw.js")
def service_worker():
    response = send_from_directory(Path(current_app.root_path) / "static" / "public", "sw.js")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response
