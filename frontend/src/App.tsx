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

    // Define Graph Nodes & Positions
    const initialNodes: GraphNode[] = [
        { id: 'planning', label: 'Supervisor Planlama', x: 230, y: 50, status: 'todo' },
        { id: 'classification', label: 'Sınıflandırma', x: 90, y: 130, status: 'todo' },
        { id: 'rag', label: 'Mevzuat Tarama', x: 90, y: 210, status: 'todo' },
        { id: 'draft', label: 'Taslak Oluşturma', x: 90, y: 290, status: 'todo' },
        { id: 'routing', label: 'Birim Yönlendirme', x: 230, y: 290, status: 'todo' },
        { id: 'document_qa', label: 'Belge Soru-Cevap', x: 230, y: 170, status: 'todo' },
        { id: 'chat', label: 'Sohbet', x: 370, y: 170, status: 'todo' },
    ];

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
                        if (!dataStr) continue;

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

            case 'planning_completed':
                const planned: string[] = event.plan_steps;
                setPlanSteps(planned);

                // Mark all initial steps as skipped if they are not in the plan, except 'planning'
                const statusMap: Record<string, 'todo' | 'running' | 'completed' | 'failed' | 'skipped'> = { planning: 'completed' };
                initialNodes.forEach(node => {
                    if (node.id !== 'planning') {
                        statusMap[node.id] = planned.map(s => s.toLowerCase()).includes(node.id.toLowerCase()) ? 'todo' : 'skipped';
                    }
                });
                setNodeStatus(statusMap);
                setCurrentLogs(prev => [
                    ...prev,
                    { time, text: `Supervisor planı oluşturdu. Çalıştırılacak adımlar: [${planned.join(', ')}]` },
                    { time, text: `Gerekçe: ${event.reasoning || 'Belirtilmedi'}` }
                ]);
                break;

            case 'node_end':
                setNodeStatus(prev => ({ ...prev, [event.node]: 'completed' }));
                if (event.result) {
                    setNodeResults(prev => ({ ...prev, [event.node]: event.result }));
                    setSelectedDetailNode(event.node); // Auto-focus detail on end
                }
                setCurrentLogs(prev => [...prev, { time, text: `${event.label} işlemi başarıyla tamamlandı.` }]);
                break;

            case 'final_result':
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
                        <p>LangGraph ile paralel karar alma ve yürütme süreçleri.</p>
                    </div>

                    <div className="visualizer-scroll">

                        {/* SVG Visual Graph */}
                        <div className="graph-container">
                            <svg width="100%" viewBox="0 0 460 360" preserveAspectRatio="xMidYMid meet">
                                {/* Connections (Links) */}
                                {/* Supervisor to classification (Document Path) */}
                                <line
                                    x1="230" y1="50"
                                    x2="90" y2="130"
                                    className={`link-line ${nodeStatus.classification || 'todo'}`}
                                />
                                {/* Supervisor to document_qa (QA Path) */}
                                <line
                                    x1="230" y1="50"
                                    x2="230" y2="170"
                                    className={`link-line ${nodeStatus.document_qa || 'todo'}`}
                                />
                                {/* Supervisor to chat (Chat Path) */}
                                <line
                                    x1="230" y1="50"
                                    x2="370" y2="170"
                                    className={`link-line ${nodeStatus.chat || 'todo'}`}
                                />

                                {/* Classification to RAG */}
                                <line
                                    x1="90" y1="130"
                                    x2="90" y2="210"
                                    className={`link-line ${nodeStatus.rag || 'todo'}`}
                                />

                                {/* RAG to Draft */}
                                <line
                                    x1="90" y1="210"
                                    x2="90" y2="290"
                                    className={`link-line ${nodeStatus.draft || 'todo'}`}
                                />

                                {/* Draft to Routing */}
                                <line
                                    x1="90" y1="290"
                                    x2="230" y2="290"
                                    className={`link-line ${nodeStatus.routing || 'todo'}`}
                                />

                                {/* Nodes */}
                                {initialNodes.map((node) => {
                                    const currentStatus = nodeStatus[node.id] || (node.id === 'planning' && activeNode === 'planning' ? 'running' : 'todo');
                                    const isActive = activeNode === node.id;

                                    return (
                                        <g
                                            key={node.id}
                                            className={`node ${isActive ? 'running' : ''} ${currentStatus}`}
                                            onClick={() => setSelectedDetailNode(node.id)}
                                            onDoubleClick={() => setSelectedDetailNode(node.id)}
                                            style={{ cursor: 'pointer' }}
                                        >
                                            <circle
                                                cx={node.x}
                                                cy={node.y}
                                                r={28}
                                                style={{
                                                    stroke: currentStatus === 'running' ? '#f59e0b' :
                                                        currentStatus === 'completed' ? '#10b981' :
                                                            currentStatus === 'skipped' ? '#374151' :
                                                                node.id === 'planning' ? '#6366f1' : '#6b7280',
                                                    strokeWidth: isActive ? 4 : 2
                                                }}
                                            />
                                            {/* Short text inside circle */}
                                            <text x={node.x} y={node.y + 3} textAnchor="middle" style={{ fill: '#ffffff', fontSize: '9px', fontWeight: 600 }}>
                                                {node.id === 'planning' ? 'PLANNER' :
                                                    node.id === 'classification' ? 'SINIF' :
                                                        node.id === 'rag' ? 'RAG' :
                                                            node.id === 'document_qa' ? 'SORU' :
                                                                node.id === 'draft' ? 'TASLAK' :
                                                                    node.id === 'routing' ? 'SEVK' :
                                                                        node.id === 'chat' ? 'SOHBET' : ''}
                                            </text>
                                            {/* Full label below circle */}
                                            <text x={node.x} y={node.y + 44} textAnchor="middle" style={{ fill: '#9ca3af', fontSize: '11px', fontWeight: 500 }}>
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
                                        {selectedDetailNode === 'planning' && 'Planlama ve Koordinasyon'}
                                        {selectedDetailNode === 'classification' && 'Sınıflandırma Detayları'}
                                        {selectedDetailNode === 'rag' && 'Mevzuat Bağlam Detayları'}
                                        {selectedDetailNode === 'draft' && 'Cevap Taslağı Detayları'}
                                        {selectedDetailNode === 'routing' && 'Yönlendirme Detayları'}
                                        {selectedDetailNode === 'document_qa' && 'Belge Soru-Cevap Detayları'}
                                        {selectedDetailNode === 'chat' && 'Sohbet Detayları'}
                                    </div>
                                    <span className={`status-badge ${nodeStatus[selectedDetailNode] || 'todo'}`}>
                                        {nodeStatus[selectedDetailNode] === 'running' ? 'Çalışıyor' :
                                            nodeStatus[selectedDetailNode] === 'completed' ? 'Tamamlandı' :
                                                nodeStatus[selectedDetailNode] === 'skipped' ? 'Atlandı' : 'Bekliyor'}
                                    </span>
                                </div>

                                {nodeResults[selectedDetailNode] ? (
                                    <>
                                        {selectedDetailNode === 'planning' && (
                                            <div className="details-grid">
                                                <div className="details-label">Oluşturulan Plan:</div>
                                                <div className="details-value">
                                                    {planSteps.length > 0 ? planSteps.join(' ➔ ') : 'Plan bulunamadı.'}
                                                </div>
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
                                                    <div className="details-value">{nodeResults.rag.rewritten_query || 'Yok'}</div>
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

                                                {/* Editor Agent Output */}
                                                {nodeResults.draft.edit_feedback && (
                                                    <div style={{ marginTop: 4 }}>
                                                        <div className="details-label" style={{ color: '#f59e0b', display: 'flex', alignItems: 'center', gap: 4 }}>
                                                            <Terminal size={12} />
                                                            Editör Ajanı Geri Bildirimi:
                                                        </div>
                                                        <div className="draft-box" style={{ background: 'rgba(245, 158, 11, 0.03)', borderColor: 'rgba(245, 158, 11, 0.15)', fontSize: '12px' }}>
                                                            {nodeResults.draft.edit_feedback}
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
                                            {selectedDetailNode === 'planning' && 'Supervisor Planlama: Girdi metnini ve parametreleri inceleyerek hangi iş adımlarının (sınıflandırma, mevzuat tarama, taslak oluşturma vb.) çalıştırılacağına karar verir.'}
                                            {selectedDetailNode === 'classification' && 'Sınıflandırma ve Ön İnceleme: Evrakın türünü belirler, zorunlu üst verileri çıkarır ve resmi kurallara uygunluğu denetler.'}
                                            {selectedDetailNode === 'rag' && 'Mevzuat Tarama: Belge içeriğine ve konusuna göre veritabanından en alakalı kanun, yönetmelik ve mevzuat maddelerini getirir.'}
                                            {selectedDetailNode === 'draft' && 'Taslak Oluşturma: Belge sınıflandırma verilerini ve mevzuat bağlamını kullanarak kurumsal, resmi bir Türkçe cevap taslağı hazırlar.'}
                                            {selectedDetailNode === 'routing' && 'Birim Yönlendirme: Hazırlanan taslak cevabın kurum içinde hangi alt birime (örn. Bilgi İşlem, Hukuk, İK) sevk edilmesi gerektiğini gerekçesiyle belirler.'}
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