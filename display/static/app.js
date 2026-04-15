const creature = document.getElementById('creature');
const status = document.getElementById('status');

let currentState = null;
let currentDetail = null;
let staleTimer = null;

const STALE_TIMEOUT_MS = 12000;

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

function resetStaleTimer() {
    clearTimeout(staleTimer);
    staleTimer = setTimeout(onStale, STALE_TIMEOUT_MS);
}

function onStale() {
    updateState('error', 'Connection lost');
    setTimeout(() => updateState('idle', null), 1500);
}

function connect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/display/ws`);

    ws.onopen = () => {
        console.log('Connected to display websocket');
        resetStaleTimer();
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        resetStaleTimer();
        if (data.type === 'ping') return;
        updateState(data.state, data.detail);
    };

    ws.onclose = () => {
        console.log('Disconnected, reconnecting in 1s...');
        clearTimeout(staleTimer);
        setTimeout(connect, 1000);
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        ws.close();
    };
}

function updateState(state, detail) {
    if (state === currentState && detail === currentDetail) return;
    currentState = state;
    currentDetail = detail;

    creature.className = 'creature ' + state;

    let label = stateLabels[state] || state;
    if (detail) {
        label += ` (${detail})`;
    }
    status.textContent = label;
}

connect();
