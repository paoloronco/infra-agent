import React, { useState } from 'react';

export default function TroubleshootingForm({ onSubmit, loading }) {
  const [query, setQuery] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (query.trim()) {
      onSubmit(query);
      setQuery('');
    }
  };

  const suggestions = [
    'Check why nginx is not responding',
    'Diagnose high CPU usage on production server',
    'Investigate database connection timeout',
    'Monitor system resources and identify bottlenecks',
  ];

  return (
    <div className="form-container">
      <h2>Ask the AI Agent</h2>
      <form onSubmit={handleSubmit}>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Describe the issue you're experiencing..."
          disabled={loading}
          rows={6}
          className="query-input"
        />
        <button type="submit" disabled={loading || !query.trim()} className="submit-btn">
          {loading ? 'Troubleshooting...' : 'Get Help'}
        </button>
      </form>

      <div className="suggestions">
        <p className="suggestions-label">Example queries:</p>
        <div className="suggestion-chips">
          {suggestions.map((sugg, i) => (
            <button
              key={i}
              onClick={() => {
                setQuery(sugg);
              }}
              className="suggestion-chip"
            >
              {sugg}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
