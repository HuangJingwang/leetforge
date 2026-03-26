const vscode = require('vscode');
const { execSync, exec } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

const DATA_DIR = path.join(os.homedir(), '.leetcode_auto');

function readJson(filename) {
    const filepath = path.join(DATA_DIR, filename);
    try {
        return JSON.parse(fs.readFileSync(filepath, 'utf-8'));
    } catch { return null; }
}

function readData(subpath) {
    const filepath = path.join(DATA_DIR, 'data', subpath);
    try { return fs.readFileSync(filepath, 'utf-8'); } catch { return ''; }
}

// ---------------------------------------------------------------------------
// Stats Tree
// ---------------------------------------------------------------------------
class StatsProvider {
    constructor() { this._onDidChange = new vscode.EventEmitter(); this.onDidChangeTreeData = this._onDidChange.event; }
    refresh() { this._onDidChange.fire(); }
    getTreeItem(el) { return el; }
    getChildren() {
        const items = [];
        try {
            // Read progress stats from the markdown table
            const content = readData('01_Hot100_进度表.md');
            if (!content) {
                items.push(new vscode.TreeItem('No data. Run: leetcode --web'));
                return items;
            }
            const lines = content.split('\n').filter(l => l.startsWith('|') && !l.includes('---'));
            const dataLines = lines.slice(1); // skip header
            let total = 0, r1Done = 0;
            for (const line of dataLines) {
                const cells = line.split('|').map(c => c.trim()).filter(Boolean);
                if (cells.length >= 8) {
                    total++;
                    if (cells[3] && cells[3] !== '' && cells[3] !== '—') r1Done++;
                }
            }
            items.push(new vscode.TreeItem(`Total: ${total} problems`));
            items.push(new vscode.TreeItem(`R1 Done: ${r1Done}/${total}`));
            items.push(new vscode.TreeItem(`R1 Remaining: ${total - r1Done}`));

            // Streak from checkin
            const profile = readJson('user_profile.json');
            if (profile && profile.username) {
                items.push(new vscode.TreeItem(`User: ${profile.username}`));
            }

            // AI usage
            const usage = readJson('ai_usage.json');
            if (usage) {
                items.push(new vscode.TreeItem(`AI Calls: ${usage.total_calls || 0}`));
            }
        } catch {
            items.push(new vscode.TreeItem('Error reading data'));
        }
        return items;
    }
}

// ---------------------------------------------------------------------------
// Review Due Tree
// ---------------------------------------------------------------------------
class ReviewProvider {
    constructor() { this._onDidChange = new vscode.EventEmitter(); this.onDidChangeTreeData = this._onDidChange.event; }
    refresh() { this._onDidChange.fire(); }
    getTreeItem(el) { return el; }
    getChildren() {
        // This reads from the progress table and computes review due
        // Simplified: show a message to use web dashboard for full review
        const items = [];
        items.push(new vscode.TreeItem('Run "leetcode --web" for full review list'));
        items.push(new vscode.TreeItem('Or "leetcode --remind" in terminal'));
        return items;
    }
}

// ---------------------------------------------------------------------------
// Struggles Tree
// ---------------------------------------------------------------------------
class StrugglesProvider {
    constructor() { this._onDidChange = new vscode.EventEmitter(); this.onDidChangeTreeData = this._onDidChange.event; }
    refresh() { this._onDidChange.fire(); }
    getTreeItem(el) { return el; }
    getChildren() {
        const items = [];
        const struggles = readJson('struggle_notebook.json');
        if (!struggles || struggles.length === 0) {
            items.push(new vscode.TreeItem('No struggles recorded'));
            return items;
        }
        // Show last 10
        const recent = struggles.slice(-10).reverse();
        for (const s of recent) {
            const item = new vscode.TreeItem(`${s.title} (${s.attempts} attempts)`);
            item.description = s.date;
            items.push(item);
        }
        return items;
    }
}

// ---------------------------------------------------------------------------
// Activate
// ---------------------------------------------------------------------------
function activate(context) {
    const statsProvider = new StatsProvider();
    const reviewProvider = new ReviewProvider();
    const strugglesProvider = new StrugglesProvider();

    vscode.window.registerTreeDataProvider('brushup.stats', statsProvider);
    vscode.window.registerTreeDataProvider('brushup.review', reviewProvider);
    vscode.window.registerTreeDataProvider('brushup.struggles', strugglesProvider);

    context.subscriptions.push(
        vscode.commands.registerCommand('brushup.sync', () => {
            vscode.window.withProgress(
                { location: vscode.ProgressLocation.Notification, title: 'BrushUp: Syncing...' },
                () => new Promise((resolve) => {
                    exec('leetcode', (err) => {
                        if (err) vscode.window.showErrorMessage(`Sync failed: ${err.message}`);
                        else vscode.window.showInformationMessage('BrushUp: Sync complete');
                        statsProvider.refresh();
                        strugglesProvider.refresh();
                        resolve();
                    });
                })
            );
        }),
        vscode.commands.registerCommand('brushup.openWeb', () => {
            exec('leetcode --web');
            vscode.window.showInformationMessage('BrushUp: Opening web dashboard...');
        }),
        vscode.commands.registerCommand('brushup.refresh', () => {
            statsProvider.refresh();
            reviewProvider.refresh();
            strugglesProvider.refresh();
            vscode.window.showInformationMessage('BrushUp: Refreshed');
        })
    );

    // Auto-refresh every 5 minutes
    const interval = setInterval(() => {
        statsProvider.refresh();
        strugglesProvider.refresh();
    }, 5 * 60 * 1000);
    context.subscriptions.push({ dispose: () => clearInterval(interval) });
}

function deactivate() {}

module.exports = { activate, deactivate };
