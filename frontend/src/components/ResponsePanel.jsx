import React from 'react';

export default function ResponsePanel({ data }) {
  return (
    <div className="response-container">
      <div className={`status ${data.success ? 'success' : 'error'}`}>
        {data.success ? '✓ Success' : '✗ Error'}
      </div>

      <div className="response-content">
        <h3>Response</h3>
        <div className="response-text">
          {data.response}
        </div>
      </div>

      {data.metadata && (
        <div className="metadata">
          <h4>Details</h4>
          <ul>
            {data.metadata.steps && <li>Steps executed: {data.metadata.steps}</li>}
            {data.metadata.error && <li>Error: {data.metadata.error}</li>}
            {data.metadata.query && (
              <li>Original query: {data.metadata.query.substring(0, 100)}...</li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
