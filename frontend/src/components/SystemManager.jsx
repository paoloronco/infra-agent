import React, { useState, useEffect } from 'react';
import axios from 'axios';

const API = '';

export default function SystemManager({ systems, onSave, onDelete, loading, error }) {
  const [name, setName] = useState('New system');
  const [host, setHost] = useState('');
  const [username, setUsername] = useState('');
  const [sshKeyPath, setSshKeyPath] = useState('');
  const [tags, setTags] = useState('ssh,production');
  const [description, setDescription] = useState('');
  const [availableKeys, setAvailableKeys] = useState([]);

  useEffect(() => {
    axios.get(`${API}/ssh-keys`)
      .then(r => setAvailableKeys(r.data))
      .catch(() => {});
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    await onSave({
      name,
      host,
      username,
      ssh_key_path: sshKeyPath,
      tags: tags.split(',').map(t => t.trim()).filter(Boolean),
      description,
    });
    setHost('');
    setUsername('');
    setSshKeyPath('');
    setTags('');
    setDescription('');
  };

  return (
    <div className="form-container">
      <h2>Managed SSH Systems</h2>
      <p className="section-description">
        Save hosts, credentials, and SSH keys. The AI uses this data to connect automatically when you mention the system name.
      </p>

      <form onSubmit={handleSubmit} className="system-form">
        <label>
          System name
          <input type="text" value={name} onChange={e => setName(e.target.value)} className="text-input" />
        </label>
        <label>
          Host / IP
          <input type="text" value={host} onChange={e => setHost(e.target.value)} className="text-input" placeholder="192.168.1.10 or hostname" />
        </label>
        <label>
          Username SSH
          <input type="text" value={username} onChange={e => setUsername(e.target.value)} className="text-input" placeholder="root" />
        </label>
        <label>
          Private SSH key
          <select value={sshKeyPath} onChange={e => setSshKeyPath(e.target.value)} className="text-input">
            <option value="">-- No key (use password) --</option>
            {availableKeys.map(k => (
              <option key={k.key_id} value={k.private_key_path}>
                {k.key_name} — {k.comment} ({k.dest_os})
              </option>
            ))}
          </select>
          {sshKeyPath && (
            <span style={{ fontSize: '0.78rem', color: '#666', marginTop: '0.25rem', display: 'block' }}>
              {sshKeyPath}
            </span>
          )}
        </label>
        <label>
          Tags (comma-separated)
          <input type="text" value={tags} onChange={e => setTags(e.target.value)} className="text-input" />
        </label>
        <label>
          Description
          <textarea value={description} onChange={e => setDescription(e.target.value)} className="text-input" rows={3} />
        </label>
        <button type="submit" className="submit-btn" disabled={loading}>
          {loading ? 'Saving...' : 'Save system'}
        </button>
      </form>

      {error && <div className="error-message">{error}</div>}

      <div className="systems-list">
        {systems.length === 0 ? (
          <div className="placeholder">No systems saved. Add one to get started.</div>
        ) : (
          systems.map(system => (
            <div key={system.id} className="system-card">
              <div className="system-card-header">
                <h3>{system.name}</h3>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                  <span className="tag-chip">{system.username}@{system.host}</span>
                  {onDelete && (
                    <button onClick={() => onDelete(system.id)}
                      style={{ background: '#e74c3c', color: '#fff', border: 'none', borderRadius: '4px', padding: '3px 10px', cursor: 'pointer', fontSize: '0.78rem' }}>
                      Delete
                    </button>
                  )}
                </div>
              </div>
              {system.ssh_key_path && (
                <p style={{ fontSize: '0.8rem', color: '#555', marginTop: '0.4rem' }}>
                  🔑 <code>{system.ssh_key_path}</code>
                </p>
              )}
              <p style={{ marginTop: '0.4rem' }}>{system.description || ''}</p>
              {system.tags?.length > 0 && (
                <div className="tag-row">
                  {system.tags.map(tag => <span key={tag} className="tag-chip">{tag}</span>)}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
