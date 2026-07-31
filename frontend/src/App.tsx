import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import {
    UploadCloud,
    Search,
    MessageSquare,
    Send,
    FileText,
    Clock,
    CheckCircle,
    Copy,
    Terminal,
    Activity
} from 'lucide-react';

interface DocumentMetadata {
    file_name: string;
    storage_path: string;
    upload_time: string;
    document_type: string;
    document_type_label: string;
    compliance_status: string;
    summary: string;
}

interface ChatMessage {
    sender: 'user' | 'assistant';
    text: string;
    status?: string;
    logs?: Array<{ time: string; text: string }>;
    details?: any;
}

interface GraphNode {
    id: string;
    label: string;
    /** Abbreviation rendered inside the circle. */
    short: string;
    /** llm = model call, rule = deterministic, io = retrieval. */
    kind: 'llm' | 'rule' | 'io';
    status: 'todo' | 'running' | 'completed' | 'failed' | 'skipped';
    x: number;
    y: number;
}

export default function App() {
    const [documents, setDocuments] = useState<DocumentMetadata[]>([]);
    const [selectedDoc, setSelectedDoc] = useState<DocumentMetadata | null>(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [uploading, setUploading] = useState(false);
    const [dragActive, setDragActive] = useState(false);

    const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
    const [inputText, setInputText] = useState('');
    const [attachActiveDoc, setAttachActiveDoc] = useState(true);
    const [loading, setLoading] = useState(false);
    const [copiedText, setCopiedText] = useState(false);
    // Text arriving token-by-token from the backend, rendered live before the
    // final_result event lands. This is what makes generation feel immediate
    // instead of showing a spinner for the whole draft.
    const [streamingText, setStreamingText] = useState('');

    // Live node execution state
    const [activeNode, setActiveNode] = useState<string | null>(null);
    const [planSteps, setPlanSteps] = useState<string[]>([]);
    const [nodeStatus, setNodeStatus] = useState<Record<string, 'todo' | 'running' | 'completed' | 'failed' | 'skipped'>>({});
    const [nodeResults, setNodeResults] = useState<Record<string, any>>({});
    const [currentLogs, setCurrentLogs] = useState<Array<{ time: string; text: string }>>([]);
    const [selectedDetailNode, setSelectedDetailNode] = useState<string | null>(null);

    const messagesEndRef = useRef<HTMLDivElement>(null);
    const logConsoleRef = useRef<HTMLDivElement>(null);
    const detailPanelRef = useRef<HTMLDivElement>(null);

    // Graph nodes and positions.
    //
    // Mirrors the actual LangGraph topology, including the parallel fan-out
    // inside the analysis sub-graph. `short` is what fits inside the circle;
    // `kind` distinguishes model calls from deterministic steps, because the
    // point of the redesign was moving work out of the model.
    const initialNodes: GraphNode[] = [
        { id: 'planning', label: 'Yönlendirici', short: 'ROUTE', kind: 'rule', x: 240, y: 44, status: 'todo' },
        { id: 'classification', label: 'Evrak Analizi', short: 'ANALİZ', kind: 'llm', x: 100, y: 122, status: 'todo' },
        { id: 'compliance', label: 'Uygunluk', short: 'UYGUN', kind: 'rule', x: 40, y: 200, status: 'todo' },
        { id: 'rag', label: 'Mevzuat', short: 'MEVZUAT', kind: 'io', x: 160, y: 200, status: 'todo' },
        { id: 'draft', label: 'Taslak', short: 'TASLAK', kind: 'llm', x: 100, y: 278, status: 'todo' },
        { id: 'verify', label: 'Doğrulama', short: 'DOĞRU', kind: 'rule', x: 100, y: 350, status: 'todo' },
        { id: 'routing', label: 'Birim Sevki', short: 'SEVK', kind: 'llm', x: 240, y: 350, status: 'todo' },
        { id: 'document_qa', label: 'Belge S-C', short: 'SORU', kind: 'llm', x: 340, y: 140, status: 'todo' },
        { id: 'chat', label: 'Sohbet', short: 'SOHBET', kind: 'llm', x: 420, y: 218, status: 'todo' },
    ];

    // Nodes that light up as a consequence of a parent step running. `compliance`
    // and `rag` live inside the analysis sub-graph and `verify` inside the
    // drafting one, so they have no plan step of their own and are driven by
    // partial_result events instead.
    const DERIVED_NODES: Record<string, string[]> = {
        classification: ['compliance', 'rag'],
        draft: ['verify'],
    };

    // Fetch documents on load
    const fetchDocuments = async () => {
        try {
            const res = await fetch('/api/v1/documents');
            const json = await res.json();
            if (json && json.data) {
                setDocuments(json.data);
            }
        } catch (e) {
            console.error('Failed to load documents', e);
        }
    };

    useEffect(() => {
        fetchDocuments();
    }, []);

    // Scroll to bottom helper
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [chatMessages, currentLogs]);

    // Scroll to detail panel when selected
    useEffect(() => {
        if (selectedDetailNode) {
            setTimeout(() => {
                detailPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 50);
        }
    }, [selectedDetailNode]);

    useEffect(() => {
        if (logConsoleRef.current) {
            logConsoleRef.current.scrollTop = logConsoleRef.current.scrollHeight;
        }
    }, [currentLogs]);

    // Handle Drag & Drop Upload
    const handleDrag = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === 'dragenter' || e.type === 'dragover') {
            setDragActive(true);
        } else if (e.type === 'dragleave') {
            setDragActive(false);
        }
    };

    const handleDrop = async (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(false);

        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            await handleUpload(e.dataTransfer.files[0]);
        }
    };

    const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            await handleUpload(e.target.files[0]);
        }
    };

    const handleUpload = async (file: File) => {
        setUploading(true);
        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch('/api/v1/documents/analyze', {
                method: 'POST',
                body: formData,
            });
            const data = await res.json();
            if (res.ok && data && data.data) {
                // Refresh docs
                await fetchDocuments();
                // Select the newly uploaded doc
                const newDoc: DocumentMetadata = {
                    file_name: data.data.file_name,
                    storage_path: data.data.storage_path,
                    upload_time: new Date().toISOString(),
                    document_type: data.data.document_type,
                    document_type_label: data.data.document_type_label,
                    compliance_status: data.data.compliance_status,
                    summary: data.data.summary,
                };
                setSelectedDoc(newDoc);

                // Add info message to chat
                setChatMessages(prev => [...prev, {
                    sender: 'assistant',
                    text: `Yeni dosya yüklendi ve analiz edildi: "${file.name}"\n\n**Belge Türü:** ${data.data.document_type_label}\n**Durum:** ${data.data.compliance_status}\n\n**Özet:** ${data.data.summary || 'Özet çıkarılamadı.'}`,
                    details: data.data
                }]);
            } else {
                alert(data.message || 'Yükleme hatası oluştu.');
            }
        } catch (e) {
            alert('Sunucuyla bağlantı hatası oluştu.');
            console.error(e);
        } finally {
            setUploading(false);
        }
    };

    // Handle SSE Chat Stream
    const handleSendMessage = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!inputText.trim() || loading) return;

        const userMessage = inputText.trim();
        setInputText('');
        setLoading(true);

        // Reset workflow/node states
        setActiveNode(null);
        setPlanSteps([]);
        setNodeStatus({});
        setNodeResults({});
        setCurrentLogs([]);
        setSelectedDetailNode(null);
        setStreamingText('');

        // Append User Message to UI
        setChatMessages(prev => [...prev, { sender: 'user', text: userMessage }]);

        try {
            const res = await fetch('/api/v1/chat/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: userMessage,
                    document_id: (attachActiveDoc && selectedDoc) ? selectedDoc.storage_path : null
                })
            });

            if (!res.ok) {
                throw new Error('Streaming failed');
            }

            const reader = res.body?.getReader();
            if (!reader) return;

            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n\n');

                // Keep the last partial line in buffer
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const dataStr = line.replace('data: ', '').trim();
                        if (!dataStr || dataStr === '[DONE]') continue;

                        try {
                            const event = JSON.parse(dataStr);
                            handleWorkflowEvent(event);
                        } catch (err) {
                            console.error('Failed to parse SSE event', err);
                        }
                    }
                }
            }
        } catch (err: any) {
            console.error(err);
            setChatMessages(prev => [...prev, {
                sender: 'assistant',
                text: 'İletişim sırasında bir hata oluştu.',
                status: 'FAILED'
            }]);
            setLoading(false);
        }
    };

    const handleWorkflowEvent = (event: any) => {
        const time = new Date().toLocaleTimeString();

        switch (event.event) {
            case 'node_start':
                setActiveNode(event.node);
                setNodeStatus(prev => ({ ...prev, [event.node]: 'running' }));
                setCurrentLogs(prev => [...prev, { time, text: `${event.label} işlemi başlatıldı...` }]);
                break;

            case 'planning_completed': {
                const planned: string[] = (event.plan_steps || []).map((s: string) => s.toLowerCase());
                setPlanSteps(planned);

                // Nodes outside the plan are greyed out. Derived nodes inherit
                // their parent's fate: `compliance` and `rag` only run if
                // `classification` does, and `verify` only if `draft` does.
                const statusMap: Record<string, 'todo' | 'running' | 'completed' | 'failed' | 'skipped'> = {
                    planning: 'completed'
                };
                initialNodes.forEach(node => {
                    if (node.id === 'planning') return;
                    const parent = Object.keys(DERIVED_NODES)
                        .find(key => DERIVED_NODES[key].includes(node.id));
                    const gate = parent ?? node.id;
                    statusMap[node.id] = planned.includes(gate) ? 'todo' : 'skipped';
                });
                setNodeStatus(statusMap);

                setCurrentLogs(prev => [
                    ...prev,
                    { time, text: `Yönlendirici planı belirledi (${event.intent || 'bilinmiyor'}): [${planned.join(' → ')}]` },
                    { time, text: `Gerekçe: ${event.reasoning || 'Belirtilmedi'}` }
                ]);
                break;
            }

            case 'node_end':
                setNodeStatus(prev => {
                    const next = { ...prev, [event.node]: 'completed' as const };
                    // Sub-graph nodes finish with their parent.
                    (DERIVED_NODES[event.node] || []).forEach(child => {
                        if (next[child] !== 'skipped') next[child] = 'completed';
                    });
                    return next;
                });
                if (event.result) {
                    setNodeResults(prev => ({
                        ...prev,
                        [event.node]: { ...(prev[event.node] || {}), ...event.result }
                    }));
                    setSelectedDetailNode(event.node); // Auto-focus detail on end
                }
                setCurrentLogs(prev => [...prev, { time, text: `${event.label} işlemi başarıyla tamamlandı.` }]);
                break;

            // Text as it is generated. Appended rather than replaced: the
            // backend sends deltas, not cumulative snapshots.
            case 'token':
                setStreamingText(prev => prev + (event.text || ''));
                break;

            // Intermediate output the backend can already show -- the
            // classification lands long before the draft finishes, and there is
            // no reason to withhold it until the run ends. These also drive the
            // sub-graph nodes, which have no plan step of their own.
            case 'partial_result':
                setNodeResults(prev => ({
                    ...prev,
                    [event.key]: { ...(prev[event.key] || {}), ...(event.value || {}) }
                }));
                if (event.key === 'classification') {
                    setNodeStatus(prev => ({ ...prev, classification: 'running', rag: 'running' }));
                    setSelectedDetailNode('classification');
                    setCurrentLogs(prev => [...prev, { time, text: 'Evrak türü ve üst veriler çıkarıldı.' }]);
                }
                if (event.key === 'compliance') {
                    setNodeStatus(prev => ({ ...prev, compliance: 'completed' }));
                    const missing = (event.value?.missing_fields || []).length;
                    setCurrentLogs(prev => [...prev, {
                        time,
                        text: missing
                            ? `Uygunluk denetimi: ${missing} eksik alan tespit edildi.`
                            : 'Uygunluk denetimi: zorunlu alanların tümü mevcut.'
                    }]);
                }
                break;

            case 'final_result':
                setStreamingText('');
                setChatMessages(prev => [...prev, {
                    sender: 'assistant',
                    text: event.reply,
                    status: event.workflow_status,
                    logs: currentLogs,
                    details: event.details
                }]);
                setActiveNode(null);
                setLoading(false);
                break;

            case 'error':
                setCurrentLogs(prev => [...prev, { time, text: `HATA: ${event.message}` }]);
                setChatMessages(prev => [...prev, {
                    sender: 'assistant',
                    text: `Hata oluştu: ${event.message}`,
                    status: 'FAILED',
                    logs: currentLogs
                }]);
                setActiveNode(null);
                setLoading(false);
                break;
        }
    };

    const copyToClipboard = (text: string) => {
        navigator.clipboard.writeText(text);
        setCopiedText(true);
        setTimeout(() => setCopiedText(false), 2000);
    };

    // Filtered documents list
    const filteredDocs = documents.filter(doc =>
        doc.file_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        doc.summary.toLowerCase().includes(searchQuery.toLowerCase())
    );

    return (
        <div className="dashboard-container">
            {/* LEFT SIDEBAR: File Upload & File List */}
            <div className="sidebar">
                <div className="logo-section">
                    <Activity size={24} className="text-cyan-400" style={{ color: '#06b6d4' }} />
                    <h1>KACHOW</h1>
                </div>

                {/* Upload Container */}
                <div className="upload-box">
                    {!uploading ? (
                        <div
                            className={`drop-zone ${dragActive ? 'drag-active' : ''}`}
                            onDragEnter={handleDrag}
                            onDragLeave={handleDrag}
                            onDragOver={handleDrag}
                            onDrop={handleDrop}
                            onClick={() => document.getElementById('file-upload-input')?.click()}
                        >
                            <div className="drop-zone-content">
                                <UploadCloud size={32} className="drop-zone-icon" />
                                <p>Dosyayı buraya sürükleyin</p>
                                <span>veya tıklayıp seçin (PDF, TXT, Resim)</span>
                            </div>
                            <input
                                id="file-upload-input"
                                type="file"
                                className="file-input"
                                accept=".pdf,.txt,.png,.jpg,.jpeg"
                                onChange={handleFileChange}
                            />
                        </div>
                    ) : (
                        <div className="uploading-spinner">
                            <div className="spinner"></div>
                            <p style={{ fontSize: '12px', color: '#9ca3af' }}>Evrak analiz ediliyor...</p>
                        </div>
                    )}
                </div>

                {/* Document List */}
                <div className="doc-list-section">
                    <div className="doc-list-header">
                        <h2>Evrak Kütüphanesi</h2>
                        <Clock size={14} className="text-gray-500" />
                    </div>

                    <div className="search-box">
                        <Search size={14} />
                        <input
                            type="text"
                            placeholder="Evraklarda ara..."
                            value={searchQuery}
                            onChange={e => setSearchQuery(e.target.value)}
                        />
                    </div>

                    <div className="doc-scroll-area">
                        {filteredDocs.length === 0 ? (
                            <div style={{ textAlign: 'center', padding: '20px', color: '#6b7280', fontSize: '12px' }}>
                                Evrak bulunamadı.
                            </div>
                        ) : (
                            filteredDocs.map((doc, idx) => (
                                <div
                                    key={idx}
                                    className={`doc-card ${selectedDoc?.storage_path === doc.storage_path ? 'selected' : ''}`}
                                    onClick={() => setSelectedDoc(doc)}
                                >
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                        <span className="doc-name">{doc.file_name}</span>
                                        <div className={`doc-status-badge ${doc.compliance_status === 'COMPLIANT' ? 'completed' : 'incomplete'}`} />
                                    </div>
                                    <p className="doc-summary-preview">{doc.summary || 'Özet yok.'}</p>
                                    <div className="doc-meta">
                                        <span className="doc-type-badge">{doc.document_type_label || doc.document_type}</span>
                                        <span>{new Date(doc.upload_time).toLocaleDateString()}</span>
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                </div>
            </div>

            {/* MIDDLE & RIGHT PANEL */}
            <div className="main-content">

                {/* MIDDLE PANEL: Chat & Logs Console */}
                <div className="chat-section">
                    <div className="chat-header">
                        <div className="chat-header-info">
                            <h2>Karar Destek Sohbeti</h2>
                            <p>Yapay zeka asistanı ile belgeleri inceleyin ve karar akışlarını izleyin.</p>
                        </div>
                        {selectedDoc && (
                            <div className="active-doc-indicator">
                                <FileText size={14} />
                                <span style={{ maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {selectedDoc.file_name}
                                </span>
                            </div>
                        )}
                    </div>

                    {/* Messages Area */}
                    <div className="messages-area">
                        {chatMessages.length === 0 && (
                            <div style={{ margin: 'auto', textAlign: 'center', maxWidth: '380px', color: '#9ca3af' }}>
                                <MessageSquare size={48} style={{ margin: '0 auto 16px auto', opacity: 0.3 }} />
                                <h3 style={{ marginBottom: '8px', fontSize: '15px' }}>Sohbete Başlayın</h3>
                                <p style={{ fontSize: '13px', color: '#6b7280' }}>
                                    Bir soru sorun veya soldaki kütüphaneden bir evrak seçerek analize başlayın.
                                </p>
                            </div>
                        )}

                        {chatMessages.map((msg, idx) => (
                            <div key={idx} className={`message-bubble ${msg.sender}`}>
                                <div className="markdown-content">
                                    <ReactMarkdown>{msg.text}</ReactMarkdown>
                                </div>
                                {msg.sender === 'assistant' && msg.details && (
                                    <div style={{ marginTop: '12px', fontSize: '11px', color: '#9ca3af', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '6px' }}>
                                        <strong>Birim Önerisi:</strong> {msg.details.routing?.routed_unit || 'Atanmadı'}
                                    </div>
                                )}
                            </div>
                        ))}

                        {/* Live generation. Rendered as a normal assistant
                            bubble so the text does not visibly jump when the
                            final_result event replaces it. */}
                        {streamingText && (
                            <div className="message-bubble assistant">
                                <div className="markdown-content">
                                    <ReactMarkdown>{streamingText}</ReactMarkdown>
                                </div>
                                <span className="streaming-caret" />
                            </div>
                        )}

                        <div ref={messagesEndRef} />
                    </div>

                    {/* Live Progress Logs Panel - Pinned above Input Area */}
                    {loading && (
                        <div className="live-logs-container-fixed">
                            <div className="live-logs-header">
                                <Terminal size={12} />
                                <span>Karar Akış Konsolu</span>
                            </div>
                            <div className="live-logs-content" ref={logConsoleRef}>
                                {currentLogs.map((log, i) => (
                                    <div key={i} className="log-entry">
                                        <span className="log-time">[{log.time}]</span>
                                        <span className="log-message">{log.text}</span>
                                    </div>
                                ))}
                                <div className="log-entry">
                                    <span className="log-time">[{new Date().toLocaleTimeString()}]</span>
                                    <span className="log-message" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                                        <span className="spinner" style={{ width: 10, height: 10, borderWidth: 1.5 }}></span>
                                        İşleniyor...
                                    </span>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Input Section */}
                    <form className="chat-input-area" onSubmit={handleSendMessage}>
                        <div className="input-controls">
                            <label className="checkbox-label">
                                <input
                                    type="checkbox"
                                    checked={attachActiveDoc}
                                    disabled={!selectedDoc}
                                    onChange={e => setAttachActiveDoc(e.target.checked)}
                                />
                                <span>Aktif Belgeyi Kullan ({selectedDoc ? selectedDoc.file_name : 'Belge Seçilmedi'})</span>
                            </label>
                        </div>

                        <div className="input-container">
                            <textarea
                                placeholder="Bir soru yazın veya resmi yazı hazırlamasını isteyin..."
                                value={inputText}
                                onChange={e => setInputText(e.target.value)}
                                onKeyDown={e => {
                                    if (e.key === 'Enter' && !e.shiftKey) {
                                        e.preventDefault();
                                        handleSendMessage(e);
                                    }
                                }}
                            />
                            <button className="send-button" type="submit" disabled={loading || !inputText.trim()}>
                                <Send size={18} />
                            </button>
                        </div>
                    </form>
                </div>

                {/* RIGHT PANEL: Live Graph Flow & Step Details */}
                <div className="visualizer-panel">
                    <div className="visualizer-header">
                        <h3>Master Planning Graph</h3>
                        <p>Deterministik yönlendirme, paralel evrak analizi ve kaynak doğrulamalı taslak üretimi.</p>
                    </div>

                    <div className="visualizer-scroll">

                        {/* SVG Visual Graph */}
                        <div className="graph-container">
                            <svg width="100%" viewBox="0 0 480 400" preserveAspectRatio="xMidYMid meet">
                                {/* Edges, drawn from the same node table as the
                                    circles so the two cannot drift apart. The
                                    `parallel` pair is the analysis fan-out. */}
                                {[
                                    { from: 'planning', to: 'classification' },
                                    { from: 'planning', to: 'document_qa' },
                                    { from: 'planning', to: 'chat' },
                                    { from: 'classification', to: 'compliance', parallel: true },
                                    { from: 'classification', to: 'rag', parallel: true },
                                    { from: 'compliance', to: 'draft' },
                                    { from: 'rag', to: 'draft' },
                                    { from: 'draft', to: 'verify' },
                                    { from: 'verify', to: 'routing' },
                                ].map((edge, i) => {
                                    const a = initialNodes.find(n => n.id === edge.from)!;
                                    const b = initialNodes.find(n => n.id === edge.to)!;
                                    const status = nodeStatus[edge.to] || 'todo';
                                    return (
                                        <line
                                            key={i}
                                            x1={a.x} y1={a.y}
                                            x2={b.x} y2={b.y}
                                            className={`link-line ${status}`}
                                            strokeDasharray={edge.parallel ? '4 3' : undefined}
                                        />
                                    );
                                })}

                                {/* Nodes */}
                                {initialNodes.map((node) => {
                                    const currentStatus = nodeStatus[node.id]
                                        || (node.id === 'planning' && activeNode === 'planning' ? 'running' : 'todo');
                                    const isActive = activeNode === node.id;

                                    // Deterministic steps get a distinct resting
                                    // colour: at a glance the graph should show
                                    // how little of the pipeline is a model call.
                                    const restingStroke =
                                        node.kind === 'rule' ? '#0ea5e9'
                                            : node.kind === 'io' ? '#a855f7'
                                                : node.id === 'planning' ? '#6366f1' : '#6b7280';

                                    const stroke =
                                        currentStatus === 'running' ? '#f59e0b'
                                            : currentStatus === 'completed' ? '#10b981'
                                                : currentStatus === 'failed' ? '#ef4444'
                                                    : currentStatus === 'skipped' ? '#374151'
                                                        : restingStroke;

                                    return (
                                        <g
                                            key={node.id}
                                            className={`node ${isActive ? 'running' : ''} ${currentStatus}`}
                                            onClick={() => setSelectedDetailNode(node.id)}
                                            style={{ cursor: 'pointer' }}
                                        >
                                            <circle
                                                cx={node.x}
                                                cy={node.y}
                                                r={26}
                                                style={{
                                                    stroke,
                                                    strokeWidth: isActive ? 4 : 2,
                                                    opacity: currentStatus === 'skipped' ? 0.4 : 1,
                                                }}
                                            />
                                            <text
                                                x={node.x} y={node.y + 3}
                                                textAnchor="middle"
                                                style={{ fill: '#ffffff', fontSize: '8.5px', fontWeight: 600 }}
                                            >
                                                {node.short}
                                            </text>
                                            <text
                                                x={node.x} y={node.y + 41}
                                                textAnchor="middle"
                                                style={{
                                                    fill: currentStatus === 'skipped' ? '#4b5563' : '#9ca3af',
                                                    fontSize: '10px',
                                                    fontWeight: 500,
                                                }}
                                            >
                                                {node.label}
                                            </text>
                                        </g>
                                    );
                                })}
                            </svg>
                        </div>

                        {/* Node Execution Details Panel */}
                        {selectedDetailNode && (
                            <div className="details-container" ref={detailPanelRef}>
                                <div className="detail-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                                    <div className="details-title" style={{ marginBottom: 0, borderBottom: 'none', paddingBottom: 0 }}>
                                        {selectedDetailNode === 'planning' && 'Yönlendirme Kararı'}
                                        {selectedDetailNode === 'classification' && 'Evrak Analizi Detayları'}
                                        {selectedDetailNode === 'compliance' && 'Uygunluk Denetimi'}
                                        {selectedDetailNode === 'rag' && 'Mevzuat Bağlam Detayları'}
                                        {selectedDetailNode === 'draft' && 'Cevap Taslağı Detayları'}
                                        {selectedDetailNode === 'verify' && 'Kaynak Doğrulama'}
                                        {selectedDetailNode === 'routing' && 'Birim Sevk Detayları'}
                                        {selectedDetailNode === 'document_qa' && 'Belge Soru-Cevap Detayları'}
                                        {selectedDetailNode === 'chat' && 'Sohbet Detayları'}
                                    </div>
                                    <span className={`status-badge ${nodeStatus[selectedDetailNode] || 'todo'}`}>
                                        {nodeStatus[selectedDetailNode] === 'running' ? 'Çalışıyor' :
                                            nodeStatus[selectedDetailNode] === 'completed' ? 'Tamamlandı' :
                                                nodeStatus[selectedDetailNode] === 'skipped' ? 'Atlandı' : 'Bekliyor'}
                                    </span>
                                </div>

                                {/* The router reports through planning_completed
                                    rather than node_end, so it has no entry in
                                    nodeResults; gate it on planSteps instead or
                                    it would always show the empty state. */}
                                {(nodeResults[selectedDetailNode]
                                    || (selectedDetailNode === 'planning' && planSteps.length > 0)) ? (
                                    <>
                                        {selectedDetailNode === 'planning' && (
                                            <div className="details-grid">
                                                <div className="details-label">Belirlenen Akış:</div>
                                                <div className="details-value">
                                                    {planSteps.length > 0 ? planSteps.join(' ➔ ') : 'Plan bulunamadı.'}
                                                </div>
                                                <div className="details-label">Karar Yöntemi:</div>
                                                <div className="details-value" style={{ color: '#0ea5e9' }}>
                                                    Deterministik kural eşleşmesi (model çağrısı yok)
                                                </div>
                                            </div>
                                        )}

                                        {selectedDetailNode === 'compliance' && (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                <div className="details-grid">
                                                    <div className="details-label">Durum:</div>
                                                    <div
                                                        className="details-value"
                                                        style={{ color: nodeResults.compliance?.compliance_status === 'COMPLIANT' ? '#10b981' : '#f59e0b' }}
                                                    >
                                                        {nodeResults.compliance?.compliance_status || 'Bilinmiyor'}
                                                    </div>
                                                    <div className="details-label">Denetlenen Kural:</div>
                                                    <div className="details-value">{nodeResults.compliance?.checked_field_count ?? 0}</div>
                                                </div>
                                                <div className="details-label" style={{ marginTop: 4 }}>Eksik Alanlar:</div>
                                                <div className="draft-box" style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d1d5db' }}>
                                                    {(nodeResults.compliance?.missing_fields || []).length > 0
                                                        ? nodeResults.compliance.missing_fields
                                                            .map((f: any) => `• ${f.label} (${f.severity}) — ${f.mevzuat}`)
                                                            .join('\n')
                                                        : 'Zorunlu alanların tümü mevcut.'}
                                                </div>
                                            </div>
                                        )}

                                        {selectedDetailNode === 'verify' && (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                <div className="details-grid">
                                                    <div className="details-label">Güven Skoru:</div>
                                                    <div
                                                        className="details-value"
                                                        style={{ fontWeight: 600, color: (nodeResults.draft?.confidence_score ?? 0) >= 70 ? '#10b981' : '#f59e0b' }}
                                                    >
                                                        %{(nodeResults.draft?.confidence_score ?? 0).toFixed(0)}
                                                    </div>
                                                    <div className="details-label">İnsan Onayı:</div>
                                                    <div className="details-value">
                                                        {nodeResults.draft?.requires_human_approval ? 'Gerekli' : 'Gerekmiyor'}
                                                    </div>
                                                    <div className="details-label">Yer Tutucu:</div>
                                                    <div className="details-value">
                                                        {nodeResults.draft?.verification?.placeholder_count ?? 0} adet
                                                    </div>
                                                </div>
                                                <div className="details-label" style={{ marginTop: 4 }}>Doğrulanamayan İfadeler:</div>
                                                <div className="draft-box" style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d1d5db' }}>
                                                    {(nodeResults.draft?.verification?.unsupported_claims || []).length > 0
                                                        ? nodeResults.draft.verification.unsupported_claims
                                                            .map((c: any) => `• [${c.kind}] "${c.value}"`)
                                                            .join('\n')
                                                        : 'Taslaktaki tüm somut bilgiler kaynakla eşleşti.'}
                                                </div>
                                                {(nodeResults.draft?.verification?.missing_structure || []).length > 0 && (
                                                    <>
                                                        <div className="details-label">Eksik Yapısal Unsurlar:</div>
                                                        <div className="draft-box" style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#f59e0b' }}>
                                                            {nodeResults.draft.verification.missing_structure.join(', ')}
                                                        </div>
                                                    </>
                                                )}
                                            </div>
                                        )}

                                        {selectedDetailNode === 'classification' && (
                                            <div className="details-grid">
                                                <div className="details-label">Belge Türü:</div>
                                                <div className="details-value">{nodeResults.classification.document_type_label || nodeResults.classification.document_type || 'Belirsiz'}</div>
                                                <div className="details-label">Uyumluluk:</div>
                                                <div className="details-value" style={{ color: nodeResults.classification.compliance_status === 'COMPLIANT' ? '#10b981' : '#ef4444' }}>
                                                    {nodeResults.classification.compliance_status}
                                                </div>
                                                {nodeResults.classification.fields && (
                                                    <>
                                                        <div className="details-label">Tarih/Sayı:</div>
                                                        <div className="details-value">{nodeResults.classification.fields.tarih || 'Çıkarılamadı'} / {nodeResults.classification.fields.sayi || 'Çıkarılamadı'}</div>
                                                    </>
                                                )}
                                                {nodeResults.classification.summary && (
                                                    <>
                                                        <div className="details-label">Özet:</div>
                                                        <div className="details-value">{nodeResults.classification.summary}</div>
                                                    </>
                                                )}
                                            </div>
                                        )}

                                        {selectedDetailNode === 'rag' && (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                <div className="details-grid">
                                                    <div className="details-label">Sorgu:</div>
                                                    <div className="details-value">{nodeResults.rag.search_query || 'Yok'}</div>
                                                </div>
                                                <div className="details-label" style={{ marginTop: 4 }}>Alınan Bağlam (Context):</div>
                                                <div className="draft-box" style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d1d5db' }}>
                                                    {nodeResults.rag.context || 'Bağlam verisi bulunamadı.'}
                                                </div>
                                            </div>
                                        )}

                                        {selectedDetailNode === 'draft' && (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                <div className="details-grid">
                                                    <div className="details-label">Yazı Türü:</div>
                                                    <div className="details-value">{nodeResults.draft.correspondence_type || 'Belirtilmedi'}</div>
                                                    <div className="details-label">Güven Skoru:</div>
                                                    <div className="details-value" style={{ fontWeight: 600, color: nodeResults.draft.confidence_score >= 70 ? '#10b981' : '#f59e0b' }}>
                                                        %{nodeResults.draft.confidence_score ? nodeResults.draft.confidence_score.toFixed(0) : '100'}
                                                    </div>
                                                    <div className="details-label">Döngü Sayısı:</div>
                                                    <div className="details-value">{nodeResults.draft.attempts || '1'} deneme</div>
                                                </div>

                                                {/* Grounding check: every claim the draft makes that
                                                    could not be traced back to the source document or
                                                    the retrieved legislation. */}
                                                {nodeResults.draft.verification?.unsupported_claims?.length > 0 && (
                                                    <div style={{ marginTop: 4 }}>
                                                        <div className="details-label" style={{ color: '#f59e0b', display: 'flex', alignItems: 'center', gap: 4 }}>
                                                            <Terminal size={12} />
                                                            Kaynakta Doğrulanamayan İfadeler:
                                                        </div>
                                                        <div className="draft-box" style={{ background: 'rgba(245, 158, 11, 0.03)', borderColor: 'rgba(245, 158, 11, 0.15)', fontSize: '12px' }}>
                                                            {nodeResults.draft.verification.unsupported_claims
                                                                .map((c: any) => `• [${c.kind}] "${c.value}" — ${c.explanation}`)
                                                                .join('\n')}
                                                        </div>
                                                    </div>
                                                )}

                                                {/* Editor/Evaluator Agent Output */}
                                                {nodeResults.draft.evaluation_notes && (
                                                    <div style={{ marginTop: 4 }}>
                                                        <div className="details-label" style={{ color: '#10b981', display: 'flex', alignItems: 'center', gap: 4 }}>
                                                            <CheckCircle size={12} />
                                                            Editör Ajanı Değerlendirme Notları:
                                                        </div>
                                                        <div className="draft-box" style={{ background: 'rgba(16, 185, 129, 0.03)', borderColor: 'rgba(16, 185, 129, 0.15)', fontSize: '12px' }}>
                                                            {nodeResults.draft.evaluation_notes}
                                                        </div>
                                                    </div>
                                                )}

                                                <div className="details-label" style={{ marginTop: 4 }}>Oluşturulan Resmi Yazı Taslağı:</div>
                                                <div className="draft-box">
                                                    {nodeResults.draft.draft || 'Taslak hazırlanamadı.'}
                                                </div>
                                                {nodeResults.draft.draft && (
                                                    <button className="copy-btn" onClick={() => copyToClipboard(nodeResults.draft.draft)}>
                                                        <Copy size={12} />
                                                        {copiedText ? 'Kopyalandı!' : 'Metni Kopyala'}
                                                    </button>
                                                )}
                                            </div>
                                        )}

                                        {selectedDetailNode === 'routing' && (
                                            <div className="details-grid">
                                                <div className="details-label">Hedef Birim:</div>
                                                <div className="details-value" style={{ fontWeight: 600, color: '#06b6d4' }}>{nodeResults.routing.routed_unit || 'Belirlenemedi'}</div>
                                                <div className="details-label">Öncelik:</div>
                                                <div className="details-value">{nodeResults.routing.priority || 'Normal'}</div>
                                                <div className="details-label">Gerekçe:</div>
                                                <div className="details-value">{nodeResults.routing.reasoning || 'Belirtilmedi.'}</div>
                                            </div>
                                        )}

                                        {selectedDetailNode === 'document_qa' && (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                <div className="details-grid">
                                                    <div className="details-label">Durum:</div>
                                                    <div className="details-value">{nodeResults.document_qa.status || 'Tamamlandı'}</div>
                                                </div>
                                                <div className="details-label">Cevap:</div>
                                                <div className="draft-box" style={{ fontFamily: 'var(--font-sans)' }}>
                                                    {nodeResults.document_qa.reply || 'Cevap bulunamadı.'}
                                                </div>
                                            </div>
                                        )}

                                        {selectedDetailNode === 'chat' && (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                <div className="details-label">Sohbet Cevabı:</div>
                                                <div className="draft-box" style={{ fontFamily: 'var(--font-sans)' }}>
                                                    {nodeResults.chat.reply || 'Yanıt yok.'}
                                                </div>
                                            </div>
                                        )}
                                    </>
                                ) : (
                                    <div style={{ padding: '12px', border: '1px dashed rgba(255,255,255,0.1)', borderRadius: '8px', color: '#9ca3af', fontSize: '11px', lineHeight: '1.6' }}>
                                        <div style={{ fontWeight: 600, color: '#ffffff', marginBottom: 4 }}>Düğüm Açıklaması:</div>
                                        <p style={{ marginBottom: 12 }}>
                                            {selectedDetailNode === 'planning' && 'Yönlendirici: Mesajı ve ekli belgeyi deterministik kurallarla eşleyerek hangi akışın çalışacağına karar verir. Kural eşleşmediğinde küçük modele tek etiketlik bir sınıflandırma sorulur.'}
                                            {selectedDetailNode === 'classification' && 'Evrak Analizi: Evrakın türünü belirler ve zorunlu üst verileri (sayı, tarih, konu, muhatap, imza) tek model çağrısında çıkarır. Etiketli alanlar ayrıca regex ile okunur ve model çıktısının üzerine yazılır.'}
                                            {selectedDetailNode === 'compliance' && 'Uygunluk Denetimi: Evrak türüne göre zorunlu alan kural tablosunu uygular. Model çağrısı içermez; tamamen yeniden üretilebilir bir küme farkı işlemidir.'}
                                            {selectedDetailNode === 'rag' && 'Mevzuat Tarama: Belge türü ve konusundan deterministik olarak kurulan sorguyla Qdrant üzerinde hibrit (yoğun + BM25) arama yapar. Uygunluk denetimiyle paralel çalışır.'}
                                            {selectedDetailNode === 'draft' && 'Taslak Oluşturma: Brief ve mevzuat bağlamını kullanarak resmî Türkçe taslağı token token üretir.'}
                                            {selectedDetailNode === 'verify' && 'Kaynak Doğrulama: Taslaktaki her sayı, tarih, kurum, tutar ve mevzuat atfının kaynak evrakta veya getirilen mevzuatta geçip geçmediğini denetler. Güven skoru buradan hesaplanır; model kendi çıktısını puanlamaz.'}
                                            {selectedDetailNode === 'routing' && 'Birim Sevki: Hazırlanan taslağın hangi alt birime sevk edileceğini gerekçesiyle belirler. Güven skoru düşükse doğrudan insan onayına yönlendirir.'}
                                            {selectedDetailNode === 'document_qa' && 'Belge Soru-Cevap: İndekslenmiş evrak metni üzerinde kullanıcının chate yazdığı soruların doğrudan cevabını arar.'}
                                            {selectedDetailNode === 'chat' && 'Genel Sohbet: Herhangi bir belge seçili olmadığında genel soruları yanıtlar.'}
                                        </p>
                                        {nodeStatus[selectedDetailNode] === 'running' && (
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#f59e0b' }}>
                                                <div className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }}></div>
                                                <span>Bu adım şu an aktif olarak yürütülüyor. Sonuçlar birazdan burada belirecektir...</span>
                                            </div>
                                        )}
                                        {nodeStatus[selectedDetailNode] === 'skipped' && (
                                            <span style={{ color: '#6b7280' }}>Bu adım mevcut planlama doğrultusunda çalıştırılmadan atlandı.</span>
                                        )}
                                        {(nodeStatus[selectedDetailNode] === 'todo' || !nodeStatus[selectedDetailNode]) && (
                                            <span style={{ color: '#6b7280' }}>Bu adım henüz sırasını bekliyor.</span>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* No Node Selected Fallback */}
                        {!selectedDetailNode && (
                            <div style={{ textAlign: 'center', padding: '24px', border: '1px dashed var(--border-glass)', borderRadius: '12px', color: '#6b7280', fontSize: '11px' }}>
                                Akış diyagramındaki herhangi bir grafik düğümüne tıklayarak tanımını ve çıktı detaylarını canlı görebilirsiniz.
                            </div>
                        )}

                    </div>
                </div>

            </div>
        </div>
    );
}