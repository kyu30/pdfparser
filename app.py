import io, csv, traceback
from pathlib import Path
from flask import Flask, request, Response, render_template_string
import pdf_parse as parse
from tempfile import TemporaryDirectory
import os

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB upload cap

# ----- plug in your real parser here -----------------------------------------

INDEX = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PDF → CSV</title>
<style>
body{font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;max-width:720px;margin:40px auto;padding:0 16px}
.card{border:1px solid #e5e7eb;border-radius:16px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,.04)}
button{padding:10px 16px;border-radius:10px;border:1px solid #111827;background:#111827;color:#fff}
input[type=file]{padding:8px;border-radius:10px;border:1px solid #e5e7eb;width:100%}
</style>
</head><body>
<h1>Parse a folder of CoStar PDFs → CSV</h1>
<div class="card">
  <form action="/process" method="post" enctype="multipart/form-data">
    <p>Select a <strong>folder</strong> (Chrome/Edge/Safari):</p>
    <input type="file" name="files" webkitdirectory directory multiple accept=".pdf">
    <p style="color:#6b7280">Tip: you can also multi-select files if your browser lacks folder picker.</p>
    <br><button type="submit">Generate CSV</button>
  </form>
</div>
</body></html>"""

@app.get("/")
def index():
    return render_template_string(INDEX)

@app.post("/process")
def process():
    files = request.files.getlist("files")
    if not files:
        return "No files received.", 400

    # whatever your parser expects to exclude
    exclude_cols = ['location', 'Geography Name', 'Property Class Name', 'Period', 'Slice', 'As Of']

    try:
        with TemporaryDirectory() as tdir:
            tdir_path = Path(tdir)

            # 1) Save every uploaded PDF into the temp directory (flatten names)
            saved = 0
            for f in files:
                if f.filename.lower().endswith(".pdf"):
                    (tdir_path / Path(f.filename).name).write_bytes(f.read())
                    saved += 1

            if saved == 0:
                return "No PDFs in upload.", 400

            # 2) Call YOUR parser once on the folder; it should write a single CSV
            combined_csv = tdir_path / "combined.csv"

            # If your parser needs the CWD to be the input dir, temporarily chdir:
            prev = os.getcwd()
            try:
                #os.chdir(str(tdir_path))
                # parse(input_dir, output_csv_path, exclude_cols)
                parse.main(str(tdir_path), str(combined_csv), exclude_cols)
            finally:
                os.chdir(prev)

            # 3) Stream the generated CSV back to the browser
            if not combined_csv.exists() or combined_csv.stat().st_size == 0:
                return "Parser ran but produced no CSV (or it was empty).", 500

            csv_bytes = combined_csv.read_bytes()
            resp = Response(csv_bytes, mimetype="text/csv")
            resp.headers["Content-Disposition"] = 'attachment; filename="parsed_pdfs.csv"'
            return resp

    except Exception as e:
        return f"Server error: {e}\n{traceback.format_exc()}", 500
    
if __name__ == '__main__':
    app.run(host = "0.0.0.0", debug=True, port = 5000)