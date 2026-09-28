from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

source = Path(r"c:\ChatX\AWSDeploymentDoc.md")
out = Path(r"c:\ChatX\AWSDeploymentDoc.pdf")
text = source.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")

width, height = A4
left = 50
right = width - 50
x = left
y = height - 50

c = canvas.Canvas(str(out), pagesize=A4)
c.setTitle("AWS Deployment Runbook")

# Main document styling
font_normal = "Helvetica"
font_heading = "Helvetica-Bold"
font_code = "Courier"

# Add a cover header
c.setFont(font_heading, 22)
c.drawString(left, y, "AWS Deployment Runbook")
y -= 28
c.setFont(font_normal, 11)
c.drawString(left, y, "Readable PDF export of the deployment documentation")
y -= 30

inside_code = False
code_lines = []

for raw_line in text.splitlines():
    stripped = raw_line.strip()

    if stripped.startswith("```"):
        if inside_code:
            # print code block
            c.setFont(font_code, 8)
            for code_line in code_lines:
                if y < 60:
                    c.showPage()
                    y = height - 50
                    c.setFont(font_code, 8)
                c.drawString(left, y, code_line[:120])
                y -= 12
            code_lines = []
            inside_code = False
            y -= 8
        else:
            if y < 60:
                c.showPage()
                y = height - 50
            inside_code = True
        continue

    if inside_code:
        code_lines.append(raw_line)
        continue

    if stripped.startswith("# "):
        if y < 70:
            c.showPage()
            y = height - 50
        c.setFont(font_heading, 14)
        c.drawString(left, y, stripped[2:])
        y -= 18
        continue

    if stripped.startswith("## "):
        if y < 70:
            c.showPage()
            y = height - 50
        c.setFont(font_heading, 12)
        c.drawString(left, y, stripped[3:])
        y -= 16
        continue

    if stripped == "---":
        if y < 60:
            c.showPage()
            y = height - 50
        c.setStrokeColorRGB(0.82, 0.85, 0.9)
        c.line(left, y, right, y)
        y -= 10
        continue

    if not stripped:
        y -= 8
        continue

    c.setFont(font_normal, 10)
    words = stripped.split()
    line = ""
    for word in words:
        candidate = (line + " " + word).strip()
        if len(candidate) <= 110:
            line = candidate
        else:
            if y < 50:
                c.showPage()
                y = height - 50
            c.drawString(left, y, line)
            y -= 12
            line = word
    if line:
        if y < 50:
            c.showPage()
            y = height - 50
        c.drawString(left, y, line)
        y -= 12

# Flush any final code block if still open
if inside_code and code_lines:
    c.setFont(font_code, 8)
    for code_line in code_lines:
        if y < 60:
            c.showPage()
            y = height - 50
        c.drawString(left, y, code_line[:120])
        y -= 12

c.save()
print(f"Created PDF: {out}")
