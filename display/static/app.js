const creature = document.getElementById('creature');
const status = document.getElementById('status');

const stateLabels = {
    idle: 'Ready',
    listening: 'Listening...',
    thinking: 'Thinking...',
    working: 'Working...',
    searching: 'Searching...',
    calculating: 'Calculating...',
    delegating: 'Asking a friend...',
    success: 'Done!',
    confused: 'Hmm...',
    error: 'Oops!',
    nutrition: 'Nutrition Mode'
};

function connect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/display/ws`);

    ws.onopen = () => {
        console.log('Connected to display websocket');
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        updateState(data.state, data.detail);
    };

    ws.onclose = () => {
        console.log('Disconnected, reconnecting in 1s...');
        setTimeout(connect, 1000);
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        ws.close();
    };
}

function updateState(state, detail) {
    creature.className = 'creature ' + state;

    let label = stateLabels[state] || state;
    if (detail) {
        label += ` (${detail})`;
    }
    status.textContent = label;
}

connect();
