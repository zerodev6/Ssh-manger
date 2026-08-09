import os
import io
import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from bson import ObjectId
import paramiko

app = FastAPI(title="Spidy VPS Manager API")

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
        db = client.get_database("spidy_vps")
    return db

# Convert MongoDB ObjectId to string for JSON serialization
def fix_id(doc):
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


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
  <title>Spidy VPS Manager - Admin Panel (Python)</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; padding: 20px; }
    .container { max-width: 950px; margin: 0 auto; }
    .card { background: #1e293b; padding: 20px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #334155; }
    input, textarea, select { width: 100%; padding: 10px; margin: 5px 0 15px; background: #0f172a; border: 1px solid #475569; color: white; border-radius: 5px; box-sizing: border-box; }
    button { background: #3b82f6; color: white; padding: 10px 15px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; }
    button.danger { background: #ef4444; }
    table { width: 100%; border-collapse: collapse; margin-top: 15px; }
    th, td { padding: 10px; border: 1px solid #334155; text-align: left; }
    th { background: #0f172a; }
  </style>
</head>
<body>
<div class="container">
  <h2>⚙️ Spidy VPS Admin Panel (Python Serverless)</h2>

  <div class="card">
    <h3 id="formTitle">Add New VPS Server</h3>
    <input type="hidden" id="serverId">
    
    <label>Server Name</label>
    <input type="text" id="name" placeholder="SG-Vultr-01">
    
    <div style="display:flex; gap:10px;">
      <div style="flex: 1;">
        <label>Country Name</label>
        <input type="text" id="country" placeholder="Singapore">
      </div>
      <div style="flex: 1;">
        <label>Country Flag Emoji</label>
        <input type="text" id="flagEmoji" placeholder="🇸🇬">
      </div>
    </div>

    <label>Host / IP Address</label>
    <input type="text" id="host" placeholder="139.180.128.50">
    
    <div style="display:flex; gap:10px;">
      <div><label>SSH Port</label><input type="number" id="sshPort" value="22"></div>
      <div><label>SSL Port</label><input type="number" id="sslPort" value="443"></div>
      <div><label>UDP Port</label><input type="number" id="udpPort" value="7300"></div>
    </div>
    
    <label>SSH Username</label>
    <input type="text" id="user" value="root">
    
    <label>Private Key (`cat ~/.ssh/id_rsa`)</label>
    <textarea id="privateKey" rows="5" placeholder="-----BEGIN OPENSSH PRIVATE KEY-----..."></textarea>
    
    <button onclick="saveServer()">Save Server</button>
    <button onclick="resetForm()" style="background:#64748b;">Cancel</button>
  </div>

  <div class="card">
    <h3>Existing Servers</h3>
    <table>
      <thead>
        <tr>
          <th>Flag & Location</th>
          <th>Server Name</th>
          <th>Host IP</th>
          <th>Ports (SSL/SSH/UDP)</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody id="serverTable"></tbody>
    </table>
  </div>
</div>

<script>
  const API_URL = '/api/admin/servers';

  async function loadServers() {
    const res = await fetch(API_URL);
    const data = await res.json();
    const tbody = document.getElementById('serverTable');
    tbody.innerHTML = data.map(s => `
      <tr>
        <td style="font-size:1.2rem;">${s.flagEmoji || '🌐'} ${s.country || 'N/A'}</td>
        <td><b>${s.name}</b></td>
        <td>${s.host}</td>
        <td>SSL:${s.sslPort} | SSH:${s.sshPort} | UDP:${s.udpPort}</td>
        <td>
          <button onclick='editServer(${JSON.stringify(s)})'>Edit</button>
          <button class="danger" onclick="deleteServer('${s._id}')">Delete</button>
        </td>
      </tr>
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

  function editServer(s) {
    document.getElementById('serverId').value = s._id;
    document.getElementById('name').value = s.name;
    document.getElementById('country').value = s.country || '';
    document.getElementById('flagEmoji').value = s.flagEmoji || '';
    document.getElementById('host').value = s.host;
    document.getElementById('sshPort').value = s.sshPort;
    document.getElementById('sslPort').value = s.sslPort;
    document.getElementById('udpPort').value = s.udpPort;
    document.getElementById('user').value = s.user;
    document.getElementById('privateKey').value = s.privateKey;
    document.getElementById('formTitle').innerText = 'Edit VPS Server';
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
    document.getElementById('privateKey').value = '';
    document.getElementById('formTitle').innerText = 'Add New VPS Server';
  }

  loadServers();
</script>
</body>
</html>
    """


# ==========================================
# 2. PUBLIC API ENDPOINTS
# ==========================================

@app.get("/")
def home():
    return {"status": "Spidy VPS Python API is Online", "admin": "/admin"}

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

    # Expiry Date Calculation
    exp_date = datetime.date.today() + datetime.timedelta(days=duration)
    formatted_exp_date = exp_date.strftime("%Y-%m-%d")

    # SSH Command
    ssh_command = f'sudo useradd -e {formatted_exp_date} -M -s /bin/false {clean_user} && echo "{clean_user}:{password}" | sudo chpasswd'

    try:
        # Load Private Key with Paramiko
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
            username=server.get("user", "root"),
            pkey=pkey,
            timeout=10
        )

        stdin, stdout, stderr = ssh.exec_command(ssh_command)
        exit_status = stdout.channel.recv_exit_status()
        err_msg = stderr.read().decode().strip()
        ssh.close()

        if exit_status == 0:
            database.accounts.insert_one({
                "username": clean_user,
                "password": password,
                "serverId": server["_id"],
                "expiredAt": formatted_exp_date,
                "createdAt": datetime.datetime.utcnow()
            })

            return {
                "success": True,
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
                "banner": "Server by spidy"
            }
        else:
            raise HTTPException(status_code=400, detail=f"User creation failed: {err_msg or 'User may already exist'}")

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
