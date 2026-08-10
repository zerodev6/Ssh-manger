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
    
    # 1. Fetch Separate SSH Servers
    db_ssh = list(database.ssh_servers.find({"isActive": True}))
    ssh_list = []
    for s in db_ssh:
        ssh_list.append({
            "id": str(s["_id"]),
            "name": f"{s.get('flagEmoji', '🌐')} {s.get('name', 'Spidy SSH Node')}",
            "flag": s.get("country", "US"),
            "host": s.get("host"),
            "ssh_port": s.get("sshPort", 22),
            "ssl_port": s.get("sslPort", 443),
            "udpgw_port": s.get("udpPort", 7300),
            "category": "SSH"
        })

    # 2. Fetch Separate V2Ray Servers
    db_v2ray = list(database.v2ray_servers.find({"isActive": True}))
    v2ray_list = []
    for v in db_v2ray:
        server_title = f"{v.get('flagEmoji', '🌐')} {v.get('name', 'Spidy V2Ray Node')}"
        host = v.get("host")
        port = v.get("v2rayPort", 8080)
        uuid = v.get("v2rayUuid", "")
        path = v.get("v2rayPath", "/v2ray")
        
        v2ray_list.append({
            "id": str(v["_id"]),
            "name": server_title,
            "flag": v.get("country", "US"),
            "host": host,
            "port": port,
            "uuid": uuid,
            "path": path,
            "vmess_link": generate_vmess_link(server_title, host, port, uuid, path),
            "vless_link": generate_vless_link(server_title, host, port, uuid, path),
            "category": "V2RAY"
        })

    # 3. Fetch Dynamic Network / SNI Rules
    db_snis = list(database.sni_hosts.find({"isActive": True}))
    network_list = []
    for sni in db_snis:
        network_list.append({
            "id": str(sni["_id"]),
            "name": sni.get("name", "Default Tunnel"),
            "category": sni.get("category", "General"),
            "tunnel_type": sni.get("tunnelType", "SSL_TLS"),
            "sni_host": sni.get("sniHost", ""),
            "payload": sni.get("payload", ""),
            "custom_dns": sni.get("customDns", "8.8.8.8")
        })

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
        "version": 2.0,
        "title": "Spidy VPN Engine",
        "ssh_servers": ssh_list,
        "v2ray_servers": v2ray_list,
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

    # Search in SSH servers first, fallback to V2Ray
    server = database.ssh_servers.find_one({"_id": ObjectId(server_id)})
    server_type = "SSH"
    if not server:
        server = database.v2ray_servers.find_one({"_id": ObjectId(server_id)})
        server_type = "V2RAY"

    if not server:
        raise HTTPException(status_code=404, detail="Selected server was not found.")

    exp_date = datetime.date.today() + datetime.timedelta(days=duration)
    formatted_exp_date = exp_date.strftime("%Y-%m-%d")

    database.accounts.insert_one({
        "username": clean_user,
        "password": password,
        "serverId": server["_id"],
        "serverType": server_type,
        "expiredAt": formatted_exp_date,
        "createdAt": datetime.datetime.utcnow()
    })

    response_data = {
        "success": True,
        "appName": "Spidy VPN",
        "type": server_type,
        "serverName": server.get("name"),
        "country": server.get("country", "United States"),
        "flagEmoji": server.get("flagEmoji", "🇺🇸"),
        "host": server.get("host"),
        "username": clean_user,
        "password": password,
        "expired": formatted_exp_date
    }

    if server_type == "SSH":
        response_data.update({
            "sslPort": server.get("sslPort", 443),
            "sshPort": server.get("sshPort", 22),
            "udpPort": server.get("udpPort", 7300),
        })
    else:
        v2_uuid = server.get("v2rayUuid") or "00000000-0000-0000-0000-000000000000"
        v2_port = server.get("v2rayPort", 8080)
        v2_path = server.get("v2rayPath", "/v2ray")
        server_title = f"{server.get('flagEmoji', '🌐')} {server.get('name', 'Spidy Node')}"
        
        response_data["v2ray"] = {
            "port": v2_port,
            "uuid": v2_uuid,
            "path": v2_path,
            "vmess": generate_vmess_link(server_title, server["host"], v2_port, v2_uuid, v2_path),
            "vless": generate_vless_link(server_title, server["host"], v2_port, v2_uuid, v2_path)
        }

    return response_data


# ==========================================
# 2. SEPARATE SSH & V2RAY ADMIN ENDPOINTS
# ==========================================

# --- SSH SERVER MANAGEMENT ---
@app.get("/api/admin/ssh-servers")
def get_ssh_servers():
    database = get_db()
    servers = list(database.ssh_servers.find())
    return [fix_id(s) for s in servers]

@app.post("/api/admin/ssh-servers")
def add_ssh_server(server_data: dict = Body(...)):
    database = get_db()
    server_data["isActive"] = True
    server_data["createdAt"] = datetime.datetime.utcnow()
    result = database.ssh_servers.insert_one(server_data)
    server_data["_id"] = str(result.inserted_id)
    return server_data

@app.delete("/api/admin/ssh-servers/{server_id}")
def delete_ssh_server(server_id: str):
    database = get_db()
    database.ssh_servers.delete_one({"_id": ObjectId(server_id)})
    return {"success": True, "message": "SSH Server deleted"}

# --- V2RAY SERVER MANAGEMENT ---
@app.get("/api/admin/v2ray-servers")
def get_v2ray_servers():
    database = get_db()
    servers = list(database.v2ray_servers.find())
    return [fix_id(s) for s in servers]

@app.post("/api/admin/v2ray-servers")
def add_v2ray_server(server_data: dict = Body(...)):
    database = get_db()
    server_data["isActive"] = True
    server_data["createdAt"] = datetime.datetime.utcnow()
    result = database.v2ray_servers.insert_one(server_data)
    server_data["_id"] = str(result.inserted_id)
    return server_data

@app.delete("/api/admin/v2ray-servers/{server_id}")
def delete_v2ray_server(server_id: str):
    database = get_db()
    database.v2ray_servers.delete_one({"_id": ObjectId(server_id)})
    return {"success": True, "message": "V2Ray Server deleted"}

# --- SNI HOST MANAGEMENT ---
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
    .container { max-width: 900px; margin: 0 auto; }
    h2 { text-align: center; color: #60a5fa; margin-bottom: 25px; }
    .card { background: var(--card-bg); padding: 20px; border-radius: 10px; margin-bottom: 20px; border: 1px solid var(--border); }
    .card-title { font-size: 1.1rem; font-weight: bold; margin-bottom: 15px; color: #93c5fd; }
    label { font-size: 0.8rem; text-transform: uppercase; color: #94a3b8; display: block; margin-top: 10px; }
    input, select { width: 100%; padding: 10px; margin-top: 5px; background: #0b0f19; border: 1px solid var(--border); color: white; border-radius: 6px; box-sizing: border-box; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
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

  <!-- USER GENERATOR -->
  <div class="card" style="border-color: #2563eb;">
    <div class="card-title">👤 Issue User Account</div>
    <label>Select Target Server</label>
    <select id="userServerId"></select>
    
    <div class="grid-2">
      <div><label>Username</label><input type="text" id="newUsername" placeholder="spidyuser"></div>
      <div><label>Password</label><input type="text" id="newPassword" placeholder="pass123"></div>
    </div>
    
    <label>Validity (Days)</label>
    <input type="number" id="newDuration" value="7">

    <button class="success" onclick="createAccount()">⚡ Issue Credentials</button>
  </div>

  <!-- ADD SSH SERVER -->
  <div class="card">
    <div class="card-title">🔑 Add SSH Server Node</div>
    <label>Server Name</label>
    <input type="text" id="ssh_name" placeholder="SG-SSH-VIP-01">
    
    <div class="grid-2">
      <div><label>Country Name</label><input type="text" id="ssh_country" placeholder="Singapore"></div>
      <div><label>Flag Emoji</label><input type="text" id="ssh_flagEmoji" placeholder="🇸🇬"></div>
    </div>

    <label>Host / IP Address</label>
    <input type="text" id="ssh_host" placeholder="129.225.117.239">
    
    <div class="grid-3">
      <div><label>SSH Port</label><input type="number" id="ssh_sshPort" value="22"></div>
      <div><label>SSL Port</label><input type="number" id="ssh_sslPort" value="443"></div>
      <div><label>UDP Port</label><input type="number" id="ssh_udpPort" value="7300"></div>
    </div>
    
    <button onclick="saveSshServer()">Save SSH Server</button>
  </div>

  <!-- ACTIVE SSH SERVERS LIST -->
  <div class="card">
    <div class="card-title">🖥️ Active SSH Servers</div>
    <div id="sshServerList">Loading...</div>
  </div>

  <!-- ADD V2RAY MAIN SERVER -->
  <div class="card">
    <div class="card-title">🚀 Add V2Ray Main Server Node</div>
    <label>Server Name</label>
    <input type="text" id="v2_name" placeholder="SG-V2Ray-VIP-01">
    
    <div class="grid-2">
      <div><label>Country Name</label><input type="text" id="v2_country" placeholder="Singapore"></div>
      <div><label>Flag Emoji</label><input type="text" id="v2_flagEmoji" placeholder="🇸🇬"></div>
    </div>

    <label>Host / IP Address</label>
    <input type="text" id="v2_host" placeholder="129.225.117.240">
    
    <div class="grid-3">
      <div><label>V2Ray Port</label><input type="number" id="v2_v2rayPort" value="8080"></div>
      <div><label>V2Ray Path</label><input type="text" id="v2_v2rayPath" value="/v2ray"></div>
      <div><label>UUID</label><input type="text" id="v2_v2rayUuid" placeholder="auto/custom-uuid"></div>
    </div>
    
    <button onclick="saveV2rayServer()">Save V2Ray Main Server</button>
  </div>

  <!-- ACTIVE V2RAY SERVERS LIST -->
  <div class="card">
    <div class="card-title">📡 Active V2Ray Main Servers</div>
    <div id="v2rayServerList">Loading...</div>
  </div>

  <!-- SNI HOST FORM -->
  <div class="card">
    <div class="card-title">🌐 Add SNI Host / Payload</div>
    <label>Network Profile Name</label>
    <input type="text" id="sniName" placeholder="Dialog Zoom Unlimited">

    <div class="grid-2">
      <div><label>Category</label><input type="text" id="sniCategory" placeholder="Dialog / Airtel / SLT"></div>
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
      <div><label>SNI Host (Bug Host)</label><input type="text" id="sniHost" placeholder="zoom.us"></div>
      <div><label>Custom DNS</label><input type="text" id="sniDns" value="8.8.8.8"></div>
    </div>

    <label>Payload (Optional)</label>
    <input type="text" id="sniPayload" placeholder="GET / HTTP/1.1[crlf]Host: zoom.us[crlf][crlf]">

    <button onclick="saveSniHost()">Save SNI Host Profile</button>
  </div>

  <!-- SNI LIST -->
  <div class="card">
    <div class="card-title">⚙️ Active SNI Hosts</div>
    <div id="sniList">Loading...</div>
  </div>
</div>

<div id="resultModal" class="modal">
  <div class="modal-content">
    <div class="card-title">🎉 Account Issued</div>
    <textarea id="accountResultText" rows="12" readonly style="width:100%; font-family: monospace; background:#0b0f19; color:#f8fafc; border:1px solid #1e293b; border-radius:6px; padding:10px;"></textarea>
    <button class="secondary" onclick="closeModal()">Close</button>
  </div>
</div>

<script>
  async function loadAllData() {
    await loadSshServers();
    await loadV2rayServers();
    await loadSniHosts();
    await populateUserDropdown();
  }

  async function populateUserDropdown() {
    const resSsh = await fetch('/api/admin/ssh-servers');
    const sshList = await resSsh.json();

    const resV2 = await fetch('/api/admin/v2ray-servers');
    const v2List = await resV2.json();

    const select = document.getElementById('userServerId');
    let html = '';

    if (sshList.length > 0) {
      html += '<optgroup label="SSH Servers">';
      html += sshList.map(s => `<option value="${s._id}">${s.flagEmoji || '🌐'} ${s.name} (${s.host}) [SSH]</option>`).join('');
      html += '</optgroup>';
    }

    if (v2List.length > 0) {
      html += '<optgroup label="V2Ray Servers">';
      html += v2List.map(s => `<option value="${s._id}">${s.flagEmoji || '🌐'} ${s.name} (${s.host}) [V2RAY]</option>`).join('');
      html += '</optgroup>';
    }

    select.innerHTML = html || '<option>No servers available</option>';
  }

  async function loadSshServers() {
    const res = await fetch('/api/admin/ssh-servers');
    const servers = await res.json();
    const list = document.getElementById('sshServerList');

    if (servers.length === 0) {
      list.innerHTML = '<p style="color:#94a3b8;">No SSH servers active.</p>';
      return;
    }

    list.innerHTML = servers.map(s => `
      <div class="server-item">
        <b>${s.flagEmoji || '🌐'} ${s.name}</b> (${s.country})<br>
        <small style="color:#94a3b8">Host: ${s.host} | SSH: ${s.sshPort} | SSL: ${s.sslPort} | UDPGW: ${s.udpPort}</small>
        <div style="margin-top:8px;">
          <button class="danger" style="padding:6px;" onclick="deleteSshServer('${s._id}')">Remove SSH Server</button>
        </div>
      </div>
    `).join('');
  }

  async function saveSshServer() {
    const body = {
      name: document.getElementById('ssh_name').value,
      country: document.getElementById('ssh_country').value,
      flagEmoji: document.getElementById('ssh_flagEmoji').value,
      host: document.getElementById('ssh_host').value,
      sshPort: parseInt(document.getElementById('ssh_sshPort').value),
      sslPort: parseInt(document.getElementById('ssh_sslPort').value),
      udpPort: parseInt(document.getElementById('ssh_udpPort').value)
    };

    await fetch('/api/admin/ssh-servers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });

    loadAllData();
  }

  async function deleteSshServer(id) {
    await fetch(`/api/admin/ssh-servers/${id}`, { method: 'DELETE' });
    loadAllData();
  }

  async function loadV2rayServers() {
    const res = await fetch('/api/admin/v2ray-servers');
    const servers = await res.json();
    const list = document.getElementById('v2rayServerList');

    if (servers.length === 0) {
      list.innerHTML = '<p style="color:#94a3b8;">No V2Ray servers active.</p>';
      return;
    }

    list.innerHTML = servers.map(s => `
      <div class="server-item">
        <b>${s.flagEmoji || '🌐'} ${s.name}</b> (${s.country})<br>
        <small style="color:#94a3b8">Host: ${s.host} | Port: ${s.v2rayPort} | Path: ${s.v2rayPath}</small>
        <div style="margin-top:8px;">
          <button class="danger" style="padding:6px;" onclick="deleteV2rayServer('${s._id}')">Remove V2Ray Server</button>
        </div>
      </div>
    `).join('');
  }

  async function saveV2rayServer() {
    const body = {
      name: document.getElementById('v2_name').value,
      country: document.getElementById('v2_country').value,
      flagEmoji: document.getElementById('v2_flagEmoji').value,
      host: document.getElementById('v2_host').value,
      v2rayPort: parseInt(document.getElementById('v2_v2rayPort').value),
      v2rayPath: document.getElementById('v2_v2rayPath').value,
      v2rayUuid: document.getElementById('v2_v2rayUuid').value
    };

    await fetch('/api/admin/v2ray-servers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });

    loadAllData();
  }

  async function deleteV2rayServer(id) {
    await fetch(`/api/admin/v2ray-servers/${id}`, { method: 'DELETE' });
    loadAllData();
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
      let text = `=== SPIDY VPN CREDENTIALS ===\nType     : ${data.type}\nServer   : ${data.flagEmoji} ${data.serverName}\nHost     : ${data.host}\nUsername : ${data.username}\nPassword : ${data.password}\nExpires  : ${data.expired}\n`;
      if (data.v2ray) {
        text += `\n--- VMESS LINK ---\n${data.v2ray.vmess}\n\n--- VLESS LINK ---\n${data.v2ray.vless}`;
      }
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

    loadAllData();
  }

  function closeModal() { document.getElementById('resultModal').style.display = 'none'; }
  async function deleteSni(id) { await fetch(`/api/admin/sni-hosts/${id}`, { method: 'DELETE' }); loadAllData(); }

  loadAllData();
</script>
</body>
</html>
    """

# Vercel Serverless Gateway Entry
handler = Mangum(app)
