import os
import io
import json
import base64
import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from bson import ObjectId
import paramiko

app = FastAPI(title="Zero VPN Backend API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB Connection
MONGO_URI = os.getenv("MONGODB_URI")
client = None
db = None

def get_db():
    global client, db
    if not MONGO_URI:
        raise HTTPException(status_code=500, detail="MONGODB_URI environment variable is missing.")
    if client is None:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client.get_database("zero_vpn")
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
# 1. EMBEDDED ADMIN PANEL ROUTE (/admin)
# ==========================================
@app.get("/admin", response_class=HTMLResponse)
def admin_panel():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Zero VPN Manager - Admin Panel</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --accent: #3b82f6;
      --danger: #ef4444;
      --success: #10b981;
      --text: #f8fafc;
      --border: #334155;
    }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 15px; }
    .container { max-width: 900px; margin: 0 auto; }
    h2 { margin-bottom: 20px; font-size: 1.5rem; text-align: center; color: #60a5fa; }
    .card { background: var(--card-bg); padding: 20px; border-radius: 12px; margin-bottom: 20px; border: 1px solid var(--border); box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3); }
    .card-title { font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; color: #93c5fd; }
    label { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px; color: #94a3b8; display: block; margin-top: 10px; }
    input, textarea, select { width: 100%; padding: 12px; margin-top: 5px; background: #0f172a; border: 1px solid var(--border); color: white; border-radius: 8px; box-sizing: border-box; font-size: 0.95rem; }
    input:focus, textarea:focus { border-color: var(--accent); outline: none; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .grid-4 { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 10px; }
    button { background: var(--accent); color: white; padding: 12px 18px; border: none; border-radius: 8px; cursor: pointer; font-weight: bold; width: 100%; margin-top: 15px; transition: 0.2s; }
    button:active { opacity: 0.8; }
    button.danger { background: var(--danger); }
    button.success { background: var(--success); }
    button.secondary { background: #475569; }
    
    .server-item { background: #0f172a; padding: 15px; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 12px; display: flex; flex-direction: column; gap: 8px; }
    .server-header { display: flex; justify-content: space-between; align-items: center; }
    .server-name { font-weight: bold; font-size: 1.1rem; }
    .server-meta { font-size: 0.85rem; color: #94a3b8; word-break: break-all; }
    .badge { background: #1e293b; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; border: 1px solid var(--border); }
    .actions { display: flex; gap: 8px; margin-top: 5px; }
    
    .modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.8); align-items: center; justify-content: center; padding: 15px; z-index: 100; }
    .modal-content { background: var(--card-bg); width: 100%; max-width: 550px; padding: 20px; border-radius: 12px; border: 1px solid var(--border); max-height: 90vh; overflow-y: auto; }
  </style>
</head>
<body>
<div class="container">
  <h2>🛡️ Zero VPN Server Admin Panel</h2>

  <!-- QUICK CREATE USER FORM -->
  <div class="card" style="border-color: #3b82f6;">
    <div class="card-title">👤 Quick Create Zero VPN Account</div>
    <label>Select Server</label>
    <select id="userServerId"></select>
    
    <div class="grid-2">
      <div><label>Username</label><input type="text" id="newUsername" placeholder="zerouser"></div>
      <div><label>Password</label><input type="text" id="newPassword" placeholder="pass123"></div>
    </div>
    
    <label>Duration (Days)</label>
    <input type="number" id="newDuration" value="7">

    <button class="success" onclick="createAccount()">⚡ Generate Zero VPN Account</button>
  </div>

  <!-- SERVER MANAGEMENT FORM -->
  <div class="card">
    <div class="card-title" id="formTitle">➕ Add Zero VPN Server</div>
    <input type="hidden" id="serverId">
    
    <label>Server Name</label>
    <input type="text" id="name" placeholder="SG-ZeroVIP-01">
    
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
      <div><label>V2Ray WS Path</label><input type="text" id="v2rayPath" value="/v2ray"></div>
      <div><label>V2Ray Static UUID</label><input type="text" id="v2rayUuid" placeholder="auto-generated if empty"></div>
    </div>
    
    <label>SSH Username</label>
    <input type="text" id="user" value="ubuntu" placeholder="ubuntu or root">
    
    <label>Private SSH Key (`cat ~/.ssh/id_rsa` or `.key` file content)</label>
    <textarea id="privateKey" rows="3" placeholder="-----BEGIN OPENSSH PRIVATE KEY-----..."></textarea>
    
    <div style="display:flex; gap:10px;">
      <button onclick="saveServer()">Save Server</button>
      <button class="secondary" onclick="resetForm()">Clear</button>
    </div>
  </div>

  <!-- SERVER LIST -->
  <div class="card">
    <div class="card-title">🖥️ Active Zero VPN Servers</div>
    <div id="serverList">Loading...</div>
  </div>
</div>

<!-- ACCOUNT CONFIG RESULT MODAL -->
<div id="resultModal" class="modal">
  <div class="modal-content">
    <div class="card-title">🎉 Zero VPN Account Created!</div>
    <textarea id="accountResultText" rows="14" readonly style="font-family: monospace; font-size: 0.85rem;"></textarea>
    <button class="success" onclick="copyAccountConfig()">📋 Copy Details</button>
    <button class="secondary" onclick="closeModal()">Close</button>
  </div>
</div>

<script>
  const API_URL = '/api/admin/servers';
  let serversCache = [];

  async function loadServers() {
    const res = await fetch(API_URL);
    serversCache = await res.json();
    
    const select = document.getElementById('userServerId');
    select.innerHTML = serversCache.map(s => `<option value="${s._id}">${s.flagEmoji || '🌐'} ${s.name} (${s.host})</option>`).join('');

    const list = document.getElementById('serverList');
    if (serversCache.length === 0) {
      list.innerHTML = '<p style="color:#94a3b8;">No servers added yet.</p>';
      return;
    }

    list.innerHTML = serversCache.map(s => `
      <div class="server-item">
        <div class="server-header">
          <div class="server-name">${s.flagEmoji || '🌐'} ${s.name} <span class="badge">${s.country || 'N/A'}</span></div>
          <span class="badge" style="color:#60a5fa;">User: ${s.user || 'root'}</span>
        </div>
        <div class="server-meta">IP: <b>${s.host}</b> | SSH: <b>${s.sshPort}</b> | SSL: <b>${s.sslPort}</b> | V2Ray: <b>${s.v2rayPort || 8080}</b></div>
        <div class="actions">
          <button class="secondary" style="margin:0;" onclick='editServer(${JSON.stringify(s)})'>Edit</button>
          <button class="danger" style="margin:0;" onclick="deleteServer('${s._id}')">Delete</button>
        </div>
      </div>
    `).join('');
  }

  async function saveServer() {
    const id = document.getElementById('serverId').value;
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
      v2rayUuid: document.getElementById('v2rayUuid').value,
      user: document.getElementById('user').value,
      privateKey: document.getElementById('privateKey').value
    };

    const method = id ? 'PUT' : 'POST';
    const url = id ? `${API_URL}/${id}` : API_URL;

    await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });

    resetForm();
    loadServers();
  }

  async function createAccount() {
    const payload = {
      serverId: document.getElementById('userServerId').value,
      username: document.getElementById('newUsername').value,
      password: document.getElementById('newPassword').value,
      duration: parseInt(document.getElementById('newDuration').value)
    };

    if (!payload.username || !payload.password) {
      alert('Please fill in username and password');
      return;
    }

    const btn = event.target;
    btn.innerText = 'Creating Account...';
    btn.disabled = true;

    try {
      const res = await fetch('/api/create-account', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      btn.innerText = '⚡ Generate Zero VPN Account';
      btn.disabled = false;

      if (res.ok) {
        const text = `=========================\n  ZERO VPN ACCOUNT DATA  \n=========================\nServer   : ${data.flagEmoji} ${data.serverName} (${data.country})\nHost IP  : ${data.host}\nUsername : ${data.username}\nPassword : ${data.password}\n-------------------------\nSSH Port : ${data.sshPort}\nSSL Port : ${data.sslPort}\nUDP Port : ${data.udpPort}\nExpires  : ${data.expired}\n=========================\n--- V2RAY (VMESS) ---\n${data.v2ray.vmess}\n\n--- V2RAY (VLESS) ---\n${data.v2ray.vless}\n=========================`;
        document.getElementById('accountResultText').value = text;
        document.getElementById('resultModal').style.display = 'flex';
      } else {
        alert('Error: ' + (data.detail || 'Failed to create user'));
      }
    } catch (e) {
      btn.innerText = '⚡ Generate Zero VPN Account';
      btn.disabled = false;
      alert('Network Error: ' + e.message);
    }
  }

  function copyAccountConfig() {
    const txt = document.getElementById('accountResultText');
    txt.select();
    document.execCommand('copy');
    alert('Account configuration copied to clipboard!');
  }

  function closeModal() {
    document.getElementById('resultModal').style.display = 'none';
  }

  function editServer(s) {
    document.getElementById('serverId').value = s._id;
    document.getElementById('name').value = s.name;
    document.getElementById('country').value = s.country || '';
    document.getElementById('flagEmoji').value = s.flagEmoji || '';
    document.getElementById('host').value = s.host;
    document.getElementById('sshPort').value = s.sshPort;
    document.getElementById('sslPort').value = s.sslPort;
    document.getElementById('udpPort').value = s.udpPort;
    document.getElementById('v2rayPort').value = s.v2rayPort || 8080;
    document.getElementById('v2rayPath').value = s.v2rayPath || '/v2ray';
    document.getElementById('v2rayUuid').value = s.v2rayUuid || '';
    document.getElementById('user').value = s.user || 'ubuntu';
    document.getElementById('privateKey').value = s.privateKey;
    document.getElementById('formTitle').innerText = '✏️ Edit Zero VPN Server';
    window.scrollTo({ top: 300, behavior: 'smooth' });
  }

  async function deleteServer(id) {
    if (confirm('Delete this server?')) {
      await fetch(`${API_URL}/${id}`, { method: 'DELETE' });
      loadServers();
    }
  }

  function resetForm() {
    document.getElementById('serverId').value = '';
    document.getElementById('name').value = '';
    document.getElementById('country').value = '';
    document.getElementById('flagEmoji').value = '';
    document.getElementById('host').value = '';
    document.getElementById('v2rayPort').value = 8080;
    document.getElementById('v2rayPath').value = '/v2ray';
    document.getElementById('v2rayUuid').value = '';
    document.getElementById('user').value = 'ubuntu';
    document.getElementById('privateKey').value = '';
    document.getElementById('formTitle').innerText = '➕ Add Zero VPN Server';
  }

  loadServers();
</script>
</body>
</html>
    """


# ==========================================
# 2. ZERO VPN APP PUBLIC ENDPOINTS
# ==========================================

@app.get("/")
def home():
    return {"status": "Zero VPN API Engine Online", "admin": "/admin", "config": "/api/v1/config.json"}

# Endpoint consumed directly by Zero VPN App on launch
@app.get("/api/v1/config.json")
def get_zero_vpn_config():
    database = get_db()
    db_servers = list(database.servers.find({"isActive": True}))
    
    server_list = []
    for s in db_servers:
        server_list.append({
            "name": f"{s.get('flagEmoji', '🌐')} {s.get('name', 'Zero Server')}",
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

    return {
        "version": 1.0,
        "title": "Zero VPN Remote Config",
        "message": "Welcome to Zero VPN - Connected to high-speed infrastructure!",
        "servers": server_list,
        "networks": [
            {
                "name": "🇱🇰 Sri Lanka Airtel Unlimited",
                "category": "Airtel",
                "tunnel_type": "SSL_TLS",
                "sni_host": "web.whatsapp.com",
                "payload": "",
                "custom_dns": "8.8.8.8"
            },
            {
                "name": "🇱🇰 Sri Lanka Dialog Zoom Bypass (SSL)",
                "category": "Dialog",
                "tunnel_type": "SSL_PAYLOAD",
                "sni_host": "zoom.us",
                "payload": "GET / HTTP/1.1[crlf]Host: zoom.us[crlf]Upgrade: websocket[crlf][crlf]",
                "custom_dns": "1.1.1.1"
            },
            {
                "name": "🌐 Direct SSH + SSL Tunnel",
                "category": "Direct",
                "tunnel_type": "DIRECT_SSL",
                "sni_host": "",
                "payload": "",
                "custom_dns": "8.8.8.8"
            }
        ]
    }

@app.get("/api/servers")
def get_public_servers():
    database = get_db()
    servers = list(database.servers.find({"isActive": True}, {"privateKey": 0}))
    return [fix_id(s) for s in servers]

@app.post("/api/create-account")
def create_ssh_account(payload: dict = Body(...)):
    username = payload.get("username")
    password = payload.get("password")
    duration = int(payload.get("duration", 7))
    server_id = payload.get("serverId")

    if not username or not password or not server_id:
        raise HTTPException(status_code=400, detail="Missing required parameters")

    clean_user = "".join(e for e in username if e.isalnum())
    database = get_db()

    try:
        server = database.servers.find_one({"_id": ObjectId(server_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Server ID format")

    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    exp_date = datetime.date.today() + datetime.timedelta(days=duration)
    formatted_exp_date = exp_date.strftime("%Y-%m-%d")

    ssh_user = server.get("user", "root")
    if ssh_user == "root":
        ssh_command = f"/usr/local/bin/create-user.sh {clean_user} {password} {duration}"
    else:
        ssh_command = f"sudo /usr/local/bin/create-user.sh {clean_user} {password} {duration}"

    try:
        key_file = io.StringIO(server["privateKey"].strip())
        
        try:
            pkey = paramiko.RSAKey.from_private_key(key_file)
        except Exception:
            key_file.seek(0)
            pkey = paramiko.Ed25519Key.from_private_key(key_file)

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        ssh.connect(
            hostname=server["host"],
            port=int(server.get("sshPort", 22)),
            username=ssh_user,
            pkey=pkey,
            timeout=10
        )

        stdin, stdout, stderr = ssh.exec_command(ssh_command)
        exit_status = stdout.channel.recv_exit_status()
        out_msg = stdout.read().decode().strip()
        err_msg = stderr.read().decode().strip()
        ssh.close()

        if exit_status == 0 and "SUCCESS" in out_msg:
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
            server_title = f"{server.get('flagEmoji', '🌐')} {server.get('name', 'Zero Server')}"

            vmess_link = generate_vmess_link(server_title, server["host"], v2_port, v2_uuid, v2_path)
            vless_link = generate_vless_link(server_title, server["host"], v2_port, v2_uuid, v2_path)

            return {
                "success": True,
                "appName": "Zero VPN",
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
                "banner": "Powered by Zero VPN",
                "v2ray": {
                    "port": v2_port,
                    "uuid": v2_uuid,
                    "path": v2_path,
                    "vmess": vmess_link,
                    "vless": vless_link
                }
            }
        else:
            raise HTTPException(status_code=400, detail=out_msg or err_msg or "Failed to create user account")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SSH Error: {str(e)}")


# ==========================================
# 3. ADMIN API ENDPOINTS
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

@app.put("/api/admin/servers/{server_id}")
def update_server(server_id: str, server_data: dict = Body(...)):
    database = get_db()
    if "_id" in server_data:
        del server_data["_id"]
    database.servers.update_one({"_id": ObjectId(server_id)}, {"$set": server_data})
    updated = database.servers.find_one({"_id": ObjectId(server_id)})
    return fix_id(updated)

@app.delete("/api/admin/servers/{server_id}")
def delete_server(server_id: str):
    database = get_db()
    database.servers.delete_one({"_id": ObjectId(server_id)})
    return {"success": True, "message": "Server deleted successfully"}
