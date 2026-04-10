// === IndexedDB helpers ===
const DB_NAME = 'sp_offline';
const DB_VERSION = 1;

function openDB() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(DB_NAME, DB_VERSION);
        req.onupgradeneeded = e => {
            const db = e.target.result;
            if (!db.objectStoreNames.contains('sets')) {
                db.createObjectStore('sets', {keyPath: 'id'});
            }
            if (!db.objectStoreNames.contains('pending')) {
                db.createObjectStore('pending', {autoIncrement: true});
            }
            if (!db.objectStoreNames.contains('meta')) {
                db.createObjectStore('meta', {keyPath: 'key'});
            }
        };
        req.onsuccess = e => resolve(e.target.result);
        req.onerror = e => reject(e.target.error);
    });
}

function dbPut(db, store, data) {
    return new Promise((resolve, reject) => {
        const tx = db.transaction(store, 'readwrite');
        tx.objectStore(store).put(data);
        tx.oncomplete = () => resolve();
        tx.onerror = e => reject(e.target.error);
    });
}

function dbGetAll(db, store) {
    return new Promise((resolve, reject) => {
        const tx = db.transaction(store, 'readonly');
        const req = tx.objectStore(store).getAll();
        req.onsuccess = () => resolve(req.result);
        req.onerror = e => reject(e.target.error);
    });
}

function dbGet(db, store, key) {
    return new Promise((resolve, reject) => {
        const tx = db.transaction(store, 'readonly');
        const req = tx.objectStore(store).get(key);
        req.onsuccess = () => resolve(req.result);
        req.onerror = e => reject(e.target.error);
    });
}

function dbClear(db, store) {
    return new Promise((resolve, reject) => {
        const tx = db.transaction(store, 'readwrite');
        tx.objectStore(store).clear();
        tx.oncomplete = () => resolve();
        tx.onerror = e => reject(e.target.error);
    });
}

// === Sync: download all data for offline use ===
async function syncData() {
    try {
        const resp = await fetch('/api/my-data');
        if (!resp.ok) return false;
        const data = await resp.json();
        const db = await openDB();
        await dbClear(db, 'sets');
        for (const s of data.sets) {
            await dbPut(db, 'sets', s);
        }
        await dbPut(db, 'meta', {key: 'lastSync', value: data.timestamp});
        return true;
    } catch (e) {
        return false;
    }
}

// === Queue practice results for later sync ===
async function queuePracticeResult(wordId, correct) {
    try {
        const db = await openDB();
        await dbPut(db, 'pending', {word_id: wordId, correct: correct, ts: Date.now()});
    } catch (e) {}
}

async function flushPendingResults() {
    try {
        const db = await openDB();
        const pending = await dbGetAll(db, 'pending');
        if (!pending.length) return;
        let sent = 0;
        for (const p of pending) {
            try {
                const resp = await fetch('/practice/log', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({word_id: p.word_id, correct: p.correct})
                });
                if (resp.ok) sent++;
            } catch (e) {
                break; // still offline
            }
        }
        if (sent === pending.length) {
            await dbClear(db, 'pending');
        }
    } catch (e) {}
}

// === Get offline data ===
async function getOfflineSets() {
    try {
        const db = await openDB();
        return await dbGetAll(db, 'sets');
    } catch (e) {
        return [];
    }
}

async function getOfflineSet(setId) {
    try {
        const db = await openDB();
        return await dbGet(db, 'sets', setId);
    } catch (e) {
        return null;
    }
}

// === Auto-sync on page load ===
document.addEventListener('DOMContentLoaded', function() {
    if (navigator.onLine) {
        flushPendingResults();
        syncData();
    }
    window.addEventListener('online', function() {
        flushPendingResults();
        syncData();
    });
});
