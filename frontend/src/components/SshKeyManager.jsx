import React, { useState, useEffect } from 'react';
import axios from 'axios';

const API = '';

const OS_OPTIONS = [
  { value: 'linux',     label: 'Linux' },
  { value: 'macos',     label: 'macOS' },
  { value: 'windows10', label: 'Windows 10' },
  { value: 'windows11', label: 'Windows 11' },
];

function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  // Fallback for HTTP (non-secure context)
  const el = document.createElement('textarea');
  el.value = text;
  el.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
  document.body.appendChild(el);
  el.focus();
  el.select();
  document.execCommand('copy');
  document.body.removeChild(el);
  return Promise.resolve();
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const handle = () => {
    copyToClipboard(text).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button onClick={handle} style={{
      padding: '3px 12px', fontSize: '0.78rem', cursor: 'pointer',
      background: copied ? '#27ae60' : '#667eea', color: '#fff',
      border: 'none', borderRadius: '4px', whiteSpace: 'nowrap', flexShrink: 0,
    }}>
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

function KeyCard({ k, onDelete }) {
  const [expanded, setExpanded] = useState(false);
  const osLabel = OS_OPTIONS.find(o => o.value === k.dest_os)?.label ?? k.dest_os;
  return (
    <div style={{
      border: '1px solid #e0e0e0', borderRadius: '8px',
      background: '#fafafa', overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '0.75rem 1rem', cursor: 'pointer', userSelect: 'none',
      }} onClick={() => setExpanded(e => !e)}>
        <div>
          <strong style={{ fontSize: '0.95rem' }}>{k.key_name}</strong>
          <span style={{ marginLeft: '0.75rem', fontSize: '0.8rem', color: '#666' }}>
            {osLabel} - {k.comment} - {new Date(k.created_at).toLocaleDateString('en-US')}
          </span>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <span style={{ fontSize: '0.8rem', color: '#999' }}>{expanded ? '▲' : '▼'}</span>
          <button onClick={e => { e.stopPropagation(); onDelete(k.key_id); }}
            style={{
              background: '#e74c3c', color: '#fff', border: 'none',
              borderRadius: '4px', padding: '3px 10px', cursor: 'pointer', fontSize: '0.78rem',
            }}>
            Delete
          </button>
        </div>
      </div>
      {expanded && (
        <div style={{ padding: '0 1rem 1rem', borderTop: '1px solid #e0e0e0' }}>
          <div style={{ marginTop: '0.75rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
              <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#444' }}>Public key</span>
              <CopyButton text={k.public_key} />
            </div>
            <pre style={{
              background: '#fff', border: '1px solid #e5e7eb', borderRadius: '6px',
              padding: '0.6rem', fontSize: '0.72rem', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
            }}>{k.public_key}</pre>
          </div>
          <p style={{ fontSize: '0.78rem', color: '#888', marginTop: '0.5rem' }}>
            Private key: <code>{k.private_key_path}</code>
          </p>
        </div>
      )}
    </div>
  );
}

export default function SshKeyManager() {
  const [keys, setKeys] = useState([]);
  const [loadingList, setLoadingList] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [systemName, setSystemName] = useState('');
  const [host, setHost] = useState('');
  const [port, setPort] = useState('22');
  const [username, setUsername] = useState('');
  const [comment, setComment] = useState('ai-agent-key');
  const [destOs, setDestOs] = useState('linux');
  const [newKey, setNewKey] = useState(null);
  const [error, setError] = useState('');

  const fetchKeys = async () => {
    setLoadingList(true);
    try {
      const res = await axios.get(`${API}/ssh-keys`);
      setKeys(res.data);
      setError('');
    } catch (err) {
      setError('Unable to load keys: ' + (err.response?.data?.detail || err.message));
    } finally {
      setLoadingList(false);
    }
  };

  useEffect(() => { fetchKeys(); }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    setCreating(true);
    setError('');
    setNewKey(null);
    try {
      const res = await axios.post(`${API}/ssh-key`, {
        comment,
        dest_os: destOs,
        host: host || null,
        port: port ? parseInt(port) : 22,
        username: username || null,
        system_name: systemName || null,
      });
      setNewKey(res.data);
      setShowForm(false);
      fetchKeys();
    } catch (err) {
      setError('Key creation error: ' + (err.response?.data?.detail || err.message));
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (keyId) => {
    if (!window.confirm('Delete this key? The private file will be removed from the filesystem.')) return;
    try {
      await axios.delete(`${API}/ssh-key/${keyId}`);
      if (newKey?.key_id === keyId) setNewKey(null);
      fetchKeys();
    } catch (err) {
      setError('Delete error: ' + (err.response?.data?.detail || err.message));
    }
  };

  const osLabel = OS_OPTIONS.find(o => o.value === newKey?.dest_os)?.label;

  return (
    <div className="form-container">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h2 style={{ margin: 0 }}>SSH Keys</h2>
        <button className="submit-btn" style={{ marginTop: 0, width: 'auto', padding: '6px 18px' }}
          onClick={() => { setShowForm(s => !s); setNewKey(null); setError(''); }}>
          {showForm ? 'Cancel' : '+ New key'}
        </button>
      </div>

      {error && <div className="error-message" style={{ marginBottom: '1rem' }}>{error}</div>}

      {/* Creation form */}
      {showForm && (
        <form onSubmit={handleCreate} style={{
          marginBottom: '1.5rem', padding: '1rem',
          background: '#f0f2ff', borderRadius: '8px', border: '1px solid #c7d2fe',
        }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 1rem' }}>
            <label>
              System name
              <input type="text" value={systemName} onChange={e => setSystemName(e.target.value)}
                className="text-input" placeholder="e.g. web-server-prod" />
            </label>
            <label>
              Target machine OS
              <select value={destOs} onChange={e => setDestOs(e.target.value)} className="text-input">
                {OS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
            <label>
              Target host / IP
              <input type="text" value={host} onChange={e => setHost(e.target.value)}
                className="text-input" placeholder="192.168.1.10 or hostname" />
            </label>
            <label>
              SSH port
              <input type="number" value={port} onChange={e => setPort(e.target.value)}
                className="text-input" placeholder="22" min="1" max="65535" />
            </label>
            <label>
              Username SSH
              <input type="text" value={username} onChange={e => setUsername(e.target.value)}
                className="text-input" placeholder="root" />
            </label>
          </div>
          <label style={{ marginTop: '0.5rem' }}>
            Key comment
            <input type="text" value={comment} onChange={e => setComment(e.target.value)} className="text-input" />
          </label>
          {host && username && (
            <p style={{ fontSize: '0.8rem', color: '#3730a3', marginTop: '0.5rem' }}>
              The system will be saved automatically and the AI can connect to it by name.
            </p>
          )}
          <button type="submit" className="submit-btn" disabled={creating} style={{ marginTop: '1rem' }}>
            {creating ? 'Generating...' : 'Create SSH key'}
          </button>
        </form>
      )}

      {/* New key result */}
      {newKey && (
        <div className="result-card" style={{ marginBottom: '1.5rem' }}>
          <h3 style={{ color: '#27ae60', marginBottom: '0.5rem' }}>Key created: {newKey.key_name}</h3>
          <p style={{ fontSize: '0.85rem', color: '#555', marginBottom: '1rem' }}>{newKey.message}</p>
          {newKey.system_saved && (
            <div style={{ background: '#e8f5e9', border: '1px solid #4caf50', borderRadius: '6px', padding: '0.6rem 0.9rem', marginBottom: '1rem', fontSize: '0.85rem', color: '#2e7d32' }}>
              System <strong>{newKey.host}</strong> saved. The AI can now connect using this name.
            </div>
          )}

          {/* Public key */}
          <div style={{ marginBottom: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
              <strong>Public key</strong>
              <CopyButton text={newKey.public_key} />
            </div>
            <pre style={{
              background: '#fff', border: '1px solid #e5e7eb', borderRadius: '6px',
              padding: '0.75rem', fontSize: '0.75rem', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
            }}>{newKey.public_key}</pre>
          </div>

          {/* Private key */}
          <div style={{ marginBottom: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
              <strong>Private key</strong>
              <CopyButton text={newKey.private_key} />
            </div>
            <pre style={{
              background: '#fff', border: '1px solid #e5e7eb', borderRadius: '6px',
              padding: '0.75rem', fontSize: '0.72rem', whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: '180px', overflowY: 'auto',
            }}>{newKey.private_key}</pre>
            <p style={{ fontSize: '0.78rem', color: '#888', marginTop: '0.3rem' }}>
              Saved automatically at: <code>{newKey.private_key_path}</code>
            </p>
          </div>

          {/* Destination command */}
          <div style={{
            background: '#1e1e2e', borderRadius: '8px', padding: '1rem',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
              <strong style={{ color: '#a6e3a1', fontSize: '0.9rem' }}>
                Command to run on the target machine ({osLabel})
              </strong>
              <CopyButton text={newKey.destination_command} />
            </div>
            <pre style={{
              color: '#cdd6f4', fontSize: '0.8rem', whiteSpace: 'pre-wrap',
              wordBreak: 'break-all', margin: 0,
            }}>{newKey.destination_command}</pre>
          </div>

          <p style={{ fontSize: '0.82rem', color: '#555', marginTop: '0.75rem' }}>
            After running the command on the target, use <code>{newKey.ssh_key_path}</code> as the identity file in the SSH configuration.
          </p>
        </div>
      )}

      {/* Keys list */}
      <div>
        <h3 style={{ marginBottom: '0.75rem' }}>Existing keys</h3>
        {loadingList ? (
          <p style={{ color: '#999' }}>Loading...</p>
        ) : keys.length === 0 ? (
          <p style={{ color: '#999', fontStyle: 'italic' }}>No keys yet. Create one with the button above.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
            {keys.map(k => <KeyCard key={k.key_id} k={k} onDelete={handleDelete} />)}
          </div>
        )}
      </div>
    </div>
  );
}
