import os
import json
import base64
import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from bson import ObjectId
from mangum import Mangum

app = FastAPI(title="Spidy VPN Backend Engine")

# Enable CORS for mobile app access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONGO_URI = os.getenv("MONGODB_URI")
client = None
db = None

def get_db():
    global client, db
    if not MONGO_URI:
        raise HTTPException(status_code=500, detail="MONGODB_URI environment variable is missing on Vercel.")
    if client is None:
        client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=2500,
            connectTimeoutMS=2500
        )
        db = client.get_database("spidy_vpn")
    return db

def fix_id(doc):
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc

def generate_vmess_link(ps_name, host, port, uuid, path="/v2ray"):
    vmess_dict = {
        "v": "2",
        "ps": ps_name,
        "add": host,
        "port": str(port),
        "id": uuid,
        "aid": "0",
        "scy": "auto",
        "net": "ws",
        "type": "none",
        "host": host,
        "path": path,
        "tls": "tls"
    }
    json_str = json.dumps(vmess_dict)
    b64_str = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
    return f"vmess://{b64_str}"

def generate_vless_link(ps_name, host, port, uuid, path="/v2ray"):
    return f"vless://{uuid}@{host}:{port}?type=ws&security=tls&path={path}#{ps_name}"


# ==========================================
# 1. PUBLIC MOBILE APP CONFIG API
# ==========================================

@app.get("/")
def home():
    return {
        "app": "Spidy VPN Backend Service",
        "status": "Online",
        "admin_dashboard": "/admin",
        "config_endpoint": "/api/v1/config.json"
    }

@app.get("/api/v1/config.json")
def get_spidy_vpn_config():
    database = get_db()
    
    # Fetch Active Servers
    db_servers = list(database.servers.find({"isActive": True}))
    server_list = []
    for s in db_servers:
        server_list.append({
            "name": f"{s.get('flagEmoji', '🌐')} {s.get('name', 'Spidy Server')}",
            "flag": s.get("country", "US"),
            "host": s.get("host"),
            "port": s.get("sslPort", 443),
            "ssh_port": s.get("sshPort", 22),
            "ssl_port": s.get("sslPort", 443),
            "udpgw_port": s.get("udpPort", 7300),
            "v2ray_port": s.get("v2rayPort", 8080),
            "v2ray_path": s.get("v2rayPath", "/v2ray"),
            "category": "VIP"
        })

    # Fetch Dynamic SNI Hosts / Network Rules
    db_snis = list(database.sni_hosts.find({"isActive": True}))
    network_list = []
    
    for sni in db_snis:
        network_list.append({
            "name": sni.get("name", "Default Tunnel"),
            "category": sni.get("category", "General"),
            "tunnel_type": sni.get("tunnelType", "SSL_TLS"),
            "sni_host": sni.get("sniHost", ""),
            "payload": sni.get("payload", ""),
            "custom_dns": sni.get("customDns", "8.8.8.8")
        })

    # Fallback if no SNIs exist in Database
    if not network_list:
        network_list = [
            {
                "name": "🌐 Direct SSL Tunnel",
                "category": "Direct",
                "tunnel_type": "DIRECT_SSL",
                "sni_host": "",
                "payload": "",
                "custom_dns": "8.8.8.8"
            }
        ]

    return {
        "version": 1.0,
        "title": "Spidy VPN Config Engine",
        "servers": server_list,
        "networks": network_list
    }

@app.post("/api/create-account")
def create_vpn_account(payload: dict = Body(...)):
    username = payload.get("username")
    password = payload.get("password")
    duration = int(payload.get("duration", 7))
    server_id = payload.get("serverId")

    if not username or not password or not server_id:
        raise HTTPException(status_code=400, detail="Missing username, password, or server ID.")

    clean_user = "".join(e for e in username if e.isalnum())
    database = get_db()

    try:
        server = database.servers.find_one({"_id": ObjectId(server_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid server reference.")

    if not server:
        raise HTTPException(status_code=404, detail="Selected server was not found.")

    exp_date = datetime.date.today() + datetime.timedelta(days=duration)
    formatted_exp_date = exp_date.strftime("%Y-%m-%d")

    # Store account in MongoDB
    database.accounts.insert_one({
        "username": clean_user,
        "password": password,
        "serverId": server["_id"],
        "expiredAt": formatted_exp_date,
        "createdAt": datetime.datetime.utcnow()
    })

    v2_uuid = server.get("v2rayUuid") or "00000000-0000-0000-0000-000000000000"
    v2_port = server.get("v2rayPort", 8080)
    v2_path = server.get("v2rayPath", "/v2ray")
    server_title = f"{server.get('flagEmoji', '🌐')} {server.get('name', 'Spidy Node')}"

    vmess_link = generate_vmess_link(server_title, server["host"], v2_port, v2_uuid, v2_path)
    vless_link = generate_vless_link(server_title, server["host"], v2_port, v2_uuid, v2_path)

    return {
        "success": True,
        "appName": "Spidy VPN",
        "serverName": server.get("name"),
        "country": server.get("country", "United States"),
        "flagEmoji": server.get("flagEmoji", "🇺🇸"),
        "host": server.get("host"),
        "sslPort": server.get("sslPort", 443),
        "sshPort": server.get("sshPort", 22),
        "udpPort": server.get("udpPort", 7300),
        "username": clean_user,
        "password": password,
        "expired": formatted_exp_date,
        "v2ray": {
            "port": v2_port,
            "uuid": v2_uuid,
            "path": v2_path,
            "vmess": vmess_link,
            "vless": vless_link
        }
    }


# ==========================================
# 2. ADMIN API & SNI MANAGEMENT
# ==========================================

@app.get("/api/admin/servers")
def get_all_servers():
    database = get_db()
    servers = list(database.servers.find())
    return [fix_id(s) for s in servers]

@app.post("/api/admin/servers")
def add_server(server_data: dict = Body(...)):
    database = get_db()
    server_data["isActive"] = True
    server_data["createdAt"] = datetime.datetime.utcnow()
    result = database.servers.insert_one(server_data)
    server_data["_id"] = str(result.inserted_id)
    return server_data

@app.delete("/api/admin/servers/{server_id}")
def delete_server(server_id: str):
    database = get_db()
    database.servers.delete_one({"_id": ObjectId(server_id)})
    return {"success": True, "message": "Server deleted"}

@app.get("/api/v1/sni-hosts")
def get_sni_hosts():
    database = get_db()
    snis = list(database.sni_hosts.find())
    return [fix_id(s) for s in snis]

@app.post("/api/admin/sni-hosts")
def add_sni_host(payload: dict = Body(...)):
    database = get_db()
    payload["createdAt"] = datetime.datetime.utcnow()
    payload["isActive"] = True
    result = database.sni_hosts.insert_one(payload)
    payload["_id"] = str(result.inserted_id)
    return payload

@app.delete("/api/admin/sni-hosts/{sni_id}")
def delete_sni_host(sni_id: str):
    database = get_db()
    database.sni_hosts.delete_one({"_id": ObjectId(sni_id)})
    return {"success": True, "message": "SNI host deleted"}


# ==========================================
# 3. EMBEDDED DASHBOARD ROUTE (/admin)
# ==========================================

@app.get("/admin", response_class=HTMLResponse)
def admin_panel():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Spidy VPN Admin Dashboard</title>
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #151c2c;
      --accent: #2563eb;
      --danger: #dc2626;
      --success: #16a34a;
      --text: #f8fafc;
      --border: #1e293b;
    }
    body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 15px; }
    .container { max-width: 850px; margin: 0 auto; }
    h2 { text-align: center; color: #60a5fa; margin-bottom: 25px; }
    .card { background: var(--card-bg); padding: 20px; border-radius: 10px; margin-bottom: 20px; border: 1px solid var(--border); }
    .card-title { font-size: 1.1rem; font-weight: bold; margin-bottom: 15px; color: #93c5fd; }
    label { font-size: 0.8rem; text-transform: uppercase; color: #94a3b8; display: block; margin-top: 10px; }
    input, select { width: 100%; padding: 10px; margin-top: 5px; background: #0b0f19; border: 1px solid var(--border); color: white; border-radius: 6px; box-sizing: border-box; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .grid-4 { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 10px; }
    button { background: var(--accent); color: white; padding: 12px; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; width: 100%; margin-top: 15px; }
    button.danger { background: var(--danger); }
    button.success { background: var(--success); }
    button.secondary { background: #334155; }
    
    .server-item { background: #0b0f19; padding: 12px; border-radius: 6px; border: 1px solid var(--border); margin-bottom: 10px; }
    .modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85); align-items: center; justify-content: center; padding: 15px; }
    .modal-content { background: var(--card-bg); width: 100%; max-width: 500px; padding: 20px; border-radius: 10px; border: 1px solid var(--border); }
  </style>
</head>
<body>
<div class="container">
  <h2>🕷️ Spidy VPN Admin Dashboard</h2>

  <!-- QUICK USER GENERATOR -->
  <div class="card" style="border-color: #2563eb;">
    <div class="card-title">👤 Quick Generate User Account</div>
    <label>Select Target VPS Server</label>
    <select id="userServerId"></select>
    
    <div class="grid-2">
      <div><label>Username</label><input type="text" id="newUsername" placeholder="spidyuser"></div>
      <div><label>Password</label><input type="text" id="newPassword" placeholder="pass123"></div>
    </div>
    
    <label>Validity (Days)</label>
    <input type="number" id="newDuration" value="7">

    <button class="success" onclick="createAccount()">⚡ Issue Spidy VPN Credentials</button>
  </div>

  <!-- SERVER ADDITION FORM -->
  <div class="card">
    <div class="card-title">➕ Add Spidy VPN Server</div>
    <label>Server Name</label>
    <input type="text" id="name" placeholder="SG-SpidyVIP-01">
    
    <div class="grid-2">
      <div><label>Country Name</label><input type="text" id="country" placeholder="Singapore"></div>
      <div><label>Flag Emoji</label><input type="text" id="flagEmoji" placeholder="🇸🇬"></div>
    </div>

    <label>Host / IP Address</label>
    <input type="text" id="host" placeholder="129.225.117.239">
    
    <div class="grid-4">
      <div><label>SSH Port</label><input type="number" id="sshPort" value="22"></div>
      <div><label>SSL Port</label><input type="number" id="sslPort" value="443"></div>
      <div><label>UDP Port</label><input type="number" id="udpPort" value="7300"></div>
      <div><label>V2Ray Port</label><input type="number" id="v2rayPort" value="8080"></div>
    </div>

    <div class="grid-2">
      <div><label>V2Ray Path</label><input type="text" id="v2rayPath" value="/v2ray"></div>
      <div><label>V2Ray UUID</label><input type="text" id="v2rayUuid" placeholder="00000000-0000-0000-0000-000000000000"></div>
    </div>
    
    <button onclick="saveServer()">Save Server Node</button>
  </div>

  <!-- SERVER LIST -->
  <div class="card">
    <div class="card-title">🖥️ Active VPS Servers</div>
    <div id="serverList">Loading...</div>
  </div>

  <!-- SNI HOST FORM -->
  <div class="card">
    <div class="card-title">🌐 Add SNI Host / Payload</div>
    <label>Network Profile Name</label>
    <input type="text" id="sniName" placeholder="Dialog Zoom Unlimited">

    <div class="grid-2">
      <div>
        <label>Category</label>
        <input type="text" id="sniCategory" placeholder="Dialog / Airtel / SLT">
      </div>
      <div>
        <label>Tunnel Type</label>
        <select id="sniTunnelType">
          <option value="SSL_TLS">SSL / TLS SNI</option>
          <option value="SSL_PAYLOAD">SSL + Payload</option>
          <option value="DIRECT_SSL">Direct SSL</option>
        </select>
      </div>
    </div>

    <div class="grid-2">
      <div>
        <label>SNI Host (Bug Host)</label>
        <input type="text" id="sniHost" placeholder="zoom.us">
      </div>
      <div>
        <label>Custom DNS</label>
        <input type="text" id="sniDns" value="8.8.8.8">
      </div>
    </div>

    <label>Payload (Optional)</label>
    <input type="text" id="sniPayload" placeholder="GET / HTTP/1.1[crlf]Host: zoom.us[crlf][crlf]">

    <button onclick="saveSniHost()">Save SNI Host Profile</button>
  </div>

  <!-- SNI LIST -->
  <div class="card">
    <div class="card-title">📡 Active SNI Hosts</div>
    <div id="sniList">Loading...</div>
  </div>
</div>

<div id="resultModal" class="modal">
  <div class="modal-content">
    <div class="card-title">🎉 Account Generated</div>
    <textarea id="accountResultText" rows="12" readonly style="width:100%; font-family: monospace; background:#0b0f19; color:#f8fafc; border:1px solid #1e293b; border-radius:6px; padding:10px;"></textarea>
    <button class="secondary" onclick="closeModal()">Close Window</button>
  </div>
</div>

<script>
  async function loadServers() {
    const res = await fetch('/api/admin/servers');
    const servers = await res.json();
    
    const select = document.getElementById('userServerId');
    select.innerHTML = servers.map(s => `<option value="${s._id}">${s.flagEmoji || '🌐'} ${s.name} (${s.host})</option>`).join('');

    const list = document.getElementById('serverList');
    if (servers.length === 0) {
      list.innerHTML = '<p style="color:#94a3b8;">No servers active.</p>';
      return;
    }

    list.innerHTML = servers.map(s => `
      <div class="server-item">
        <b>${s.flagEmoji || '🌐'} ${s.name}</b> (${s.country})<br>
        <small style="color:#94a3b8">Host: ${s.host} | SSL: ${s.sslPort} | V2Ray: ${s.v2rayPort}</small>
        <div style="margin-top:8px;">
          <button class="danger" style="padding:6px;" onclick="deleteServer('${s._id}')">Remove Server</button>
        </div>
      </div>
    `).join('');
  }

  async function saveServer() {
    const body = {
      name: document.getElementById('name').value,
      country: document.getElementById('country').value,
      flagEmoji: document.getElementById('flagEmoji').value,
      host: document.getElementById('host').value,
      sshPort: parseInt(document.getElementById('sshPort').value),
      sslPort: parseInt(document.getElementById('sslPort').value),
      udpPort: parseInt(document.getElementById('udpPort').value),
      v2rayPort: parseInt(document.getElementById('v2rayPort').value),
      v2rayPath: document.getElementById('v2rayPath').value,
      v2rayUuid: document.getElementById('v2rayUuid').value
    };

    await fetch('/api/admin/servers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });

    loadServers();
  }

  async function createAccount() {
    const payload = {
      serverId: document.getElementById('userServerId').value,
      username: document.getElementById('newUsername').value,
      password: document.getElementById('newPassword').value,
      duration: parseInt(document.getElementById('newDuration').value)
    };

    const res = await fetch('/api/create-account', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (res.ok) {
      const text = `=== SPIDY VPN CREDENTIALS ===\nServer   : ${data.flagEmoji} ${data.serverName}\nHost     : ${data.host}\nUsername : ${data.username}\nPassword : ${data.password}\nExpires  : ${data.expired}\n\n--- VMESS LINK ---\n${data.v2ray.vmess}\n\n--- VLESS LINK ---\n${data.v2ray.vless}`;
      document.getElementById('accountResultText').value = text;
      document.getElementById('resultModal').style.display = 'flex';
    } else {
      alert('Error: ' + (data.detail || 'Creation failed'));
    }
  }

  async function loadSniHosts() {
    const res = await fetch('/api/v1/sni-hosts');
    const snis = await res.json();
    const list = document.getElementById('sniList');

    if (snis.length === 0) {
      list.innerHTML = '<p style="color:#94a3b8;">No SNI hosts configured.</p>';
      return;
    }

    list.innerHTML = snis.map(s => `
      <div class="server-item">
        <b>${s.name}</b> (${s.category})<br>
        <small style="color:#94a3b8">SNI: ${s.sniHost || 'None'} | Type: ${s.tunnelType}</small>
        <div style="margin-top:8px;">
          <button class="danger" style="padding:6px;" onclick="deleteSni('${s._id}')">Remove SNI</button>
        </div>
      </div>
    `).join('');
  }

  async function saveSniHost() {
    const body = {
      name: document.getElementById('sniName').value,
      category: document.getElementById('sniCategory').value,
      tunnelType: document.getElementById('sniTunnelType').value,
      sniHost: document.getElementById('sniHost').value,
      customDns: document.getElementById('sniDns').value,
      payload: document.getElementById('sniPayload').value
    };

    await fetch('/api/admin/sni-hosts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });

    loadSniHosts();
  }

  function closeModal() { document.getElementById('resultModal').style.display = 'none'; }
  async function deleteServer(id) { await fetch(`/api/admin/servers/${id}`, { method: 'DELETE' }); loadServers(); }
  async function deleteSni(id) { await fetch(`/api/admin/sni-hosts/${id}`, { method: 'DELETE' }); loadSniHosts(); }

  loadServers();
  loadSniHosts();
</script>
</body>
</html>
    """

# Vercel Serverless Gateway Entry
handler = Mangum(app)
