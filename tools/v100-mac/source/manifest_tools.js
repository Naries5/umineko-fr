ObjC.import('Foundation');

function readUtf8(path) {
    const data = $.NSData.dataWithContentsOfFile($(path));
    if (!data) throw new Error("Impossible de lire " + path);
    const s = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding);
    return ObjC.unwrap(s);
}

function loadManifest(path) { return JSON.parse(readUtf8(path)); }
function field(v) {
    if (v === null || v === undefined) return "";
    return String(v).replace(/\t/g, " ").replace(/\r?\n/g, " ");
}
function norm(v) { return field(v).replace(/\\/g, "/"); }

function run(argv) {
    const cmd = argv[0];
    const m = loadManifest(argv[1]);
    if (cmd === "version") return field(m.version || "");
    if (cmd === "notes") return field(m.notes || "");
    if (cmd === "files") {
        return (m.files || []).map(f =>
            [norm(f.path), field(f.sha256), field(f.size || 0), field(f.packageId)].join("\t")
        ).join("\n");
    }
    if (cmd === "packages") {
        return (m.packages || []).map(p =>
            [field(p.id), field(p.downloadUrl), field(p.sha256), field(p.size || 0)].join("\t")
        ).join("\n");
    }
    if (cmd === "deletePaths") return (m.deletePaths || []).map(norm).join("\n");
    throw new Error("Commande inconnue : " + cmd);
}
