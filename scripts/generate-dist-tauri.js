const fs = require("fs");
const path = require("path");

const distDir = path.resolve(__dirname, "..", "dist-tauri");
const indexPath = path.join(distDir, "index.html");

const htmlContent = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Ankigen</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #111; color: #eee; }
    .card { max-width: 520px; padding: 24px; border: 1px solid rgba(255,255,255,0.08); border-radius: 18px; box-shadow: 0 24px 60px rgba(0,0,0,0.35); }
    h1 { margin: 0 0 12px; font-size: 2rem; }
    p { margin: 8px 0; line-height: 1.6; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Ankigen</h1>
    <p>Starting the local server…</p>
    <p>If the interface does not appear, make sure the application is allowed through your firewall and try again.</p>
  </div>
</body>
</html>`;

if (!fs.existsSync(distDir)) {
  fs.mkdirSync(distDir, { recursive: true });
}

fs.writeFileSync(indexPath, htmlContent, "utf8");
console.log(`Generated ${indexPath}`);
