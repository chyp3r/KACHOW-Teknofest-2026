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
    Activity,
    AlertTriangle,
    FilePlus,
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

interface EvrakFields {
    sayi?: string | null;
    tarih?: string | null;
    konu?: string | null;
    muhatap?: string | null;
    gonderen_kurum?: string | null;
    ilgi?: string[];
    ekler?: string[];
    imza_sahibi?: string | null;
    imza_unvani?: string | null;
    gizlilik_derecesi?: string | null;
    ivedilik?: string | null;
    basvuran_adi?: string | null;
    adres?: string | null;
    iletisim?: string | null;
    entities?: string[];
}

const EVRAK_FIELD_LABELS: Record<keyof EvrakFields, string> = {
    sayi: 'Sayı',
    tarih: 'Tarih',
    konu: 'Konu',
    muhatap: 'Muhatap',
    gonderen_kurum: 'Gönderen Kurum',
    ilgi: 'İlgi',
    ekler: 'Ekler',
    imza_sahibi: 'İmza Sahibi',
    imza_unvani: 'İmza Unvanı',
    gizlilik_derecesi: 'Gizlilik Derecesi',
    ivedilik: 'İvedilik',
    basvuran_adi: 'Başvuran Adı',
    adres: 'Adres',
    iletisim: 'İletişim',
    entities: 'Tespit Edilen Varlıklar',
};

interface MissingFieldItem {
    key: string;
    label: string;
    severity: string;
    mevzuat: string;
    reason: string;
}

interface MevzuatRef {
    mevzuat: string;
    aciklama: string;
}

interface FullAnalysis {
    file_name: string;
    storage_path: string;
    analysis_id?: string;
    extraction: { extractor: string; page_count: number; char_count: number; used_ocr: boolean; scrubbed_markers?: string[] };
    document_type: string;
    document_type_label: string;
    summary: string;
    fields: EvrakFields;
    missing_fields: MissingFieldItem[];
    compliance_status: string;
    mevzuat_references: MevzuatRef[];
}

interface InfoQuestion {
    key: string;
    label: string;
    why?: string;
    example?: string | null;
    required?: boolean;
}

interface InterruptState {
    kind: 'missing_information' | 'draft_approval';
    interruptId: string;
    payload: {
        questions?: InfoQuestion[];
        draft?: string;
        verification?: any;
        judge?: any;
        combined_score?: number;
        requires_human_approval?: boolean;
    };
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
    /** llm = model call, rule = deterministic, io = retrieval/human. */
    kind: 'llm' | 'rule' | 'io';
    status: 'todo' | 'running' | 'completed' | 'failed' | 'skipped';
    x: number;
    y: number;
}

const CORRESPONDENCE_TYPE_FALLBACK = [
    { value: 'cover_letter', label: 'Üst yazı' },
    { value: 'response_letter', label: 'Cevap yazısı' },
    { value: 'information_notice', label: 'Bilgilendirme metni' },
    { value: 'other_official', label: 'Diğer resmî yazışma' },
];

// Speed-vs-quality tradeoff sent to the backend as `reasoning_level`; see
// backend/app/ai/reasoning_levels.py for what each tier actually changes.
type ReasoningLevel = 'fast' | 'balanced' | 'deep';
const REASONING_LEVELS: Array<{ value: ReasoningLevel; label: string }> = [
    { value: 'fast', label: 'Hızlı' },
    { value: 'balanced', label: 'Dengeli' },
    { value: 'deep', label: 'Derin' },
];

// Anonim, tarayıcıya özgü konuşma kimliği. localStorage'da kalıcılaştırılır,
// böylece sayfa yenileme/yeni sekme AYNI checkpoint thread'ini (ve rolling
// özetini) yeniden kullanır. Gerçek kullanıcı kimliği DEĞİLDİR: farklı
// tarayıcı/cihaz veya temizlenmiş localStorage yeni bir thread başlatır.
const CLIENT_SESSION_STORAGE_KEY = 'kachow_client_session_id';

function getOrCreateClientSessionId(): string {
    try {
        const existing = window.localStorage.getItem(CLIENT_SESSION_STORAGE_KEY);
        if (existing) return existing;
        const fresh = `web:${crypto.randomUUID()}`;
        window.localStorage.setItem(CLIENT_SESSION_STORAGE_KEY, fresh);
        return fresh;
    } catch {
        // Private browsing / storage disabled: degrade to a fresh id for
        // this tab only, same as today's behavior.
        return `web:${crypto.randomUUID()}`;
    }
}

export default function App() {
    const [documents, setDocuments] = useState<DocumentMetadata[]>([]);
    const [selectedDoc, setSelectedDoc] = useState<DocumentMetadata | null>(null);
    const [fullAnalysis, setFullAnalysis] = useState<FullAnalysis | null>(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [uploading, setUploading] = useState(false);
    const [dragActive, setDragActive] = useState(false);

    const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
    const [inputText, setInputText] = useState('');
    const [attachActiveDoc, setAttachActiveDoc] = useState(false);
    const [reasoningLevel, setReasoningLevel] = useState<ReasoningLevel>('balanced');
    const [loading, setLoading] = useState(false);
    const [copiedText, setCopiedText] = useState(false);
    // Text arriving token-by-token from the backend, rendered live before the
    // final_result event lands. This is what makes generation feel immediate
    // instead of showing a spinner for the whole draft.
    const [streamingText, setStreamingText] = useState('');

    // Checkpointer thread id for this conversation. Resolved server-side and
    // handed back as the first SSE event when the client doesn't supply one;
    // required to call /chat/resume against a paused run.
    const [sessionId, setSessionId] = useState<string | null>(() => getOrCreateClientSessionId());
    const [pendingInterrupt, setPendingInterrupt] = useState<InterruptState | null>(null);
    const [resumeAnswers, setResumeAnswers] = useState<Record<string, string>>({});
    const [resumeInstructions, setResumeInstructions] = useState('');
    const seenInterruptIds = useRef<Set<string>>(new Set());

    // Task 2 standalone drafting form (POST /documents/draft), independent of
    // the chat flow -- this endpoint previously had no UI caller at all.
    const [draftFormOpen, setDraftFormOpen] = useState(false);
    const [correspondenceTypes, setCorrespondenceTypes] = useState(CORRESPONDENCE_TYPE_FALLBACK);
    const [draftCorrespondenceType, setDraftCorrespondenceType] = useState('');
    const [draftReasoningLevel, setDraftReasoningLevel] = useState<ReasoningLevel>('balanced');
    const [draftInstructions, setDraftInstructions] = useState('');
    const [draftSubmitting, setDraftSubmitting] = useState(false);
    const [draftResult, setDraftResult] = useState<any | null>(null);

    // Live node execution state
    const [activeNode, setActiveNode] = useState<string | null>(null);
    const [planSteps, setPlanSteps] = useState<string[]>([]);
    const [nodeStatus, setNodeStatus] = useState<Record<string, 'todo' | 'running' | 'completed' | 'failed' | 'skipped'>>({});
    const [nodeResults, setNodeResults] = useState<Record<string, any>>({});
    const [nodeMeta, setNodeMeta] = useState<Record<string, any>>({});
    // Tool calls the assistant agent made this turn (search_document,
    // get_document_details, get_document_text, search_legislation) -- see the
    // 'tool_call' SSE event. Shown in the assist node's detail panel.
    const [toolCalls, setToolCalls] = useState<Array<{ tool: string; args: any; time: string }>>([]);
    const [currentLogs, setCurrentLogs] = useState<Array<{ time: string; text: string }>>([]);
    const [selectedDetailNode, setSelectedDetailNode] = useState<string | null>(null);

    const messagesEndRef = useRef<HTMLDivElement>(null);
    const logConsoleRef = useRef<HTMLDivElement>(null);
    const detailPanelRef = useRef<HTMLDivElement>(null);
    // handleWorkflowEvent is a fresh closure every render, but the SAME
    // instance keeps getting called for the lifetime of one SSE stream (the
    // reader loop captures it once in consumeSSEStream). Reading `currentLogs`
    // state directly inside it -- e.g. when building the final chat bubble --
    // would see whatever it was at stream-start, not the entries appended by
    // every node_start/node_end processed since. This ref is always current;
    // appendLog() below is the only way currentLogs is ever mutated, so the
    // two never drift apart.
    const currentLogsRef = useRef<Array<{ time: string; text: string }>>([]);
    const appendLog = (text: string) => {
        const entry = { time: new Date().toLocaleTimeString(), text };
        currentLogsRef.current = [...currentLogsRef.current, entry];
        setCurrentLogs(currentLogsRef.current);
    };

    // Graph nodes and positions.
    //
    // Mirrors the actual LangGraph topology, including the parallel fan-out
    // inside the analysis sub-graph and the reflexion/HITL additions: `judge`
    // runs beside `verify` (two distinct quality mechanisms), `revise` loops
    // back into `draft`, and `human_gate` is where the run pauses for a person.
    const initialNodes: GraphNode[] = [
        { id: 'planning', label: 'Yönlendirici', short: 'ROUTE', kind: 'rule', x: 240, y: 40, status: 'todo' },
        { id: 'classification', label: 'Evrak Analizi', short: 'ANALİZ', kind: 'llm', x: 100, y: 112, status: 'todo' },
        { id: 'compliance', label: 'Uygunluk', short: 'UYGUN', kind: 'rule', x: 40, y: 184, status: 'todo' },
        { id: 'rag', label: 'Mevzuat', short: 'MEVZUAT', kind: 'io', x: 160, y: 184, status: 'todo' },
        { id: 'draft', label: 'Taslak', short: 'TASLAK', kind: 'llm', x: 100, y: 256, status: 'todo' },
        { id: 'revise', label: 'Revizyon', short: 'REVİZE', kind: 'rule', x: 20, y: 256, status: 'todo' },
        { id: 'verify', label: 'Doğrulama', short: 'DOĞRU', kind: 'rule', x: 60, y: 328, status: 'todo' },
        { id: 'judge', label: 'Kalite Yargıcı', short: 'YARGIÇ', kind: 'llm', x: 160, y: 328, status: 'todo' },
        { id: 'human_gate', label: 'İnsan Onayı', short: 'ONAY', kind: 'io', x: 110, y: 396, status: 'todo' },
        { id: 'routing', label: 'Birim Sevki', short: 'SEVK', kind: 'llm', x: 240, y: 396, status: 'todo' },
        { id: 'assist', label: 'Asistan', short: 'ASİSTAN', kind: 'llm', x: 400, y: 170, status: 'todo' },
    ];

    // `parallel` marks the analysis fan-out, `back` marks the revision loop --
    // typed explicitly so every element can carry either optional flag without
    // TypeScript inferring a strict per-literal union that would reject
    // `edge.parallel`/`edge.back` on the elements that omit them.
    const graphEdges: Array<{ from: string; to: string; parallel?: boolean; back?: boolean }> = [
        { from: 'planning', to: 'classification' },
        { from: 'planning', to: 'assist' },
        { from: 'classification', to: 'compliance', parallel: true },
        { from: 'classification', to: 'rag', parallel: true },
        { from: 'compliance', to: 'draft' },
        { from: 'rag', to: 'draft' },
        { from: 'draft', to: 'verify' },
        { from: 'draft', to: 'judge' },
        { from: 'verify', to: 'human_gate' },
        { from: 'judge', to: 'human_gate' },
        { from: 'human_gate', to: 'routing' },
        { from: 'verify', to: 'revise', back: true },
        { from: 'revise', to: 'draft', back: true },
    ];

    // Fetch documents on load
    const fetchDocuments = async () => {
        try {
            const res = await fetch('/api/v1/documents');
            const json = await res.json();
            const items = json?.data?.items ?? json?.data;
            if (Array.isArray(items)) {
                setDocuments(items);
            }
        } catch (e) {
            console.error('Failed to load documents', e);
        }
    };

    const fetchCorrespondenceTypes = async () => {
        try {
            const res = await fetch('/api/v1/documents/correspondence-types');
            const json = await res.json();
            if (Array.isArray(json?.data) && json.data.length > 0) {
                setCorrespondenceTypes(json.data);
            }
        } catch (e) {
            console.error('Failed to load correspondence types', e);
        }
    };

    useEffect(() => {
        fetchDocuments();
        fetchCorrespondenceTypes();
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

    // Load the full analysis (all EvrakField values, missing_fields,
    // mevzuat_references) whenever a document is selected. The sidebar list
    // only ever carries the 7-field library projection.
    useEffect(() => {
        if (!selectedDoc) {
            setFullAnalysis(null);
            return;
        }
        let cancelled = false;
        (async () => {
            try {
                const res = await fetch(`/api/v1/documents/${selectedDoc.storage_path}`);
                const json = await res.json();
                if (!cancelled && res.ok && json?.data) {
                    setFullAnalysis(json.data);
                }
            } catch (e) {
                console.error('Failed to load full analysis', e);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [selectedDoc]);

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
                setFullAnalysis(data.data);

                const missingCount = (data.data.missing_fields || []).length;
                const mevzuatCount = (data.data.mevzuat_references || []).length;

                // Add info message to chat
                setChatMessages(prev => [...prev, {
                    sender: 'assistant',
                    text: `Yeni dosya yüklendi ve analiz edildi: "${file.name}"\n\n**Belge Türü:** ${data.data.document_type_label}\n**Durum:** ${data.data.compliance_status}\n**Eksik Alan:** ${missingCount} · **Mevzuat Önerisi:** ${mevzuatCount}\n\n**Özet:** ${data.data.summary || 'Özet çıkarılamadı.'}`,
                    details: data.data
                }]);
            } else {
                setChatMessages(prev => [...prev, {
                    sender: 'assistant',
                    text: `Yükleme hatası: ${data?.error?.message || data?.message || 'Bilinmeyen hata.'}`,
                    status: 'FAILED',
                }]);
            }
        } catch (e) {
            setChatMessages(prev => [...prev, {
                sender: 'assistant',
                text: 'Sunucuyla bağlantı hatası oluştu.',
                status: 'FAILED',
            }]);
            console.error(e);
        } finally {
            setUploading(false);
        }
    };

    // Reset the live workflow visualisation before a new run (fresh message or resume).
    const resetWorkflowView = () => {
        setActiveNode(null);
        setPlanSteps([]);
        setNodeStatus({});
        setNodeResults({});
        setNodeMeta({});
        setToolCalls([]);
        currentLogsRef.current = [];
        setCurrentLogs([]);
        setSelectedDetailNode(null);
        setStreamingText('');
    };

    // Shared SSE consumption: both a fresh message (/chat/stream) and a
    // resume (/chat/resume) speak the exact same event vocabulary.
    const consumeSSEStream = async (response: Response) => {
        if (!response.ok) {
            throw new Error('Streaming failed');
        }
        const reader = response.body?.getReader();
        if (!reader) return;

        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const dataStr = line.replace('data: ', '').trim();
                    if (!dataStr || dataStr === '[DONE]') continue;
                    try {
                        handleWorkflowEvent(JSON.parse(dataStr));
                    } catch (err) {
                        console.error('Failed to parse SSE event', err);
                    }
                }
            }
        }
    };

    // Handle SSE Chat Stream
    const handleSendMessage = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!inputText.trim() || loading) return;

        const userMessage = inputText.trim();
        setInputText('');
        setLoading(true);
        setPendingInterrupt(null);
        resetWorkflowView();

        setChatMessages(prev => [...prev, { sender: 'user', text: userMessage }]);

        try {
            const res = await fetch('/api/v1/chat/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: userMessage,
                    session_id: sessionId,
                    document_id: (attachActiveDoc && selectedDoc) ? selectedDoc.storage_path : null,
                    reasoning_level: reasoningLevel,
                })
            });
            await consumeSSEStream(res);
        } catch (err: any) {
            console.error(err);
            setChatMessages(prev => [...prev, {
                sender: 'assistant',
                text: 'İletişim sırasında bir hata oluştu.',
                status: 'FAILED'
            }]);
        } finally {
            // Always clears, regardless of which terminal event (or none) the
            // stream ended on -- previously only final_result/error did this,
            // so a stream ending at [DONE] with neither (e.g. a bare pause)
            // left the send button permanently disabled.
            setLoading(false);
        }
    };

    const handleResumeSubmit = async (action: 'answer' | 'approve' | 'revise' | 'reject') => {
        if (!pendingInterrupt || !sessionId) return;
        setLoading(true);
        resetWorkflowView();

        try {
            const res = await fetch('/api/v1/chat/resume', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: sessionId,
                    action,
                    answers: resumeAnswers,
                    instructions: resumeInstructions,
                }),
            });
            setPendingInterrupt(null);
            setResumeAnswers({});
            setResumeInstructions('');
            await consumeSSEStream(res);
        } catch (err) {
            console.error(err);
            setChatMessages(prev => [...prev, {
                sender: 'assistant',
                text: 'Devam işlemi sırasında bir hata oluştu.',
                status: 'FAILED',
            }]);
        } finally {
            setLoading(false);
        }
    };

    const handleWorkflowEvent = (event: any) => {
        switch (event.event) {
            // First event of every stream: the resolved checkpointer thread_id.
            case 'session':
                if (event.thread_id) setSessionId(event.thread_id);
                break;

            case 'node_start':
                setActiveNode(event.node);
                setNodeStatus(prev => ({ ...prev, [event.node]: 'running' }));
                if (event.meta) setNodeMeta(prev => ({ ...prev, [event.node]: event.meta }));
                // A second draft attempt (revision) streams under the same
                // "draft" node id -- clear any in-progress text on every
                // node_start rather than only the first, or the two attempts
                // would visually concatenate.
                if (event.node === 'draft') setStreamingText('');
                appendLog(`${event.label} işlemi başlatıldı...`);
                break;

            case 'planning_completed': {
                const planned: string[] = (event.plan_steps || []).map((s: string) => s.toLowerCase());
                setPlanSteps(planned);

                // Sub-graph nodes (compliance, rag under classification; verify,
                // judge, revise, human_gate under draft) now emit their own
                // real events, so they are simply gated on their parent's plan
                // membership rather than derived/simulated.
                const parentOf: Record<string, string> = {
                    compliance: 'classification',
                    rag: 'classification',
                    verify: 'draft',
                    judge: 'draft',
                    revise: 'draft',
                    human_gate: 'draft',
                };
                const statusMap: Record<string, 'todo' | 'running' | 'completed' | 'failed' | 'skipped'> = {
                    planning: 'completed'
                };
                initialNodes.forEach(node => {
                    if (node.id === 'planning') return;
                    const gate = parentOf[node.id] ?? node.id;
                    statusMap[node.id] = planned.includes(gate) ? 'todo' : 'skipped';
                });
                setNodeStatus(statusMap);

                appendLog(`Yönlendirici planı belirledi (${event.intent || 'bilinmiyor'}): [${planned.join(' → ')}]`);
                appendLog(`Gerekçe: ${event.reasoning || 'Belirtilmedi'}`);
                break;
            }

            case 'node_end':
                setNodeStatus(prev => ({ ...prev, [event.node]: 'completed' }));
                if (event.meta) setNodeMeta(prev => ({ ...prev, [event.node]: event.meta }));
                if (event.result) {
                    setNodeResults(prev => ({
                        ...prev,
                        [event.node]: { ...(prev[event.node] || {}), ...event.result }
                    }));
                    setSelectedDetailNode(event.node); // Auto-focus detail on end
                }
                appendLog(`${event.label} işlemi başarıyla tamamlandı.`);
                break;

            case 'node_error':
                setNodeStatus(prev => ({ ...prev, [event.node]: event.fatal === false ? prev[event.node] : 'failed' }));
                appendLog(
                    event.fatal === false
                        ? `UYARI (${event.label}): ${event.message}`
                        : `HATA (${event.label}): ${event.message}`
                );
                break;

            case 'node_skipped':
                setNodeStatus(prev => ({ ...prev, [event.node]: 'skipped' }));
                appendLog(`Atlandı (${event.label}): ${event.reason}`);
                break;

            // Text as it is generated. Appended rather than replaced: the
            // backend sends deltas, not cumulative snapshots.
            case 'token':
                setStreamingText(prev => prev + (event.text || ''));
                break;

            // The assistant agent called a tool (search_document,
            // get_document_details, get_document_text, search_legislation)
            // before answering -- see app.ai.agents.assistant.run_stream.
            case 'tool_call':
                setToolCalls(prev => [...prev, {
                    tool: event.tool,
                    args: event.args || {},
                    time: new Date().toLocaleTimeString(),
                }]);
                appendLog(`Araç çağrıldı: ${event.tool}`);
                break;

            // Intermediate output the backend can already show -- the
            // classification lands long before the draft finishes, and there is
            // no reason to withhold it until the run ends.
            case 'partial_result':
                setNodeResults(prev => ({
                    ...prev,
                    [event.key]: { ...(prev[event.key] || {}), ...(event.value || {}) }
                }));
                if (event.key === 'classification') {
                    setNodeStatus(prev => ({ ...prev, classification: 'running' }));
                    setSelectedDetailNode('classification');
                    appendLog('Evrak türü ve üst veriler çıkarıldı.');
                }
                if (event.key === 'compliance') {
                    setNodeStatus(prev => ({ ...prev, compliance: 'completed' }));
                    const missing = (event.value?.missing_fields || []).length;
                    appendLog(
                        missing
                            ? `Uygunluk denetimi: ${missing} eksik alan tespit edildi.`
                            : 'Uygunluk denetimi: zorunlu alanların tümü mevcut.'
                    );
                }
                break;

            // The run paused at the human-in-the-loop gate. interrupt_id
            // dedupes against LangGraph's own replay-before-resume semantics
            // (human_gate_node re-executes everything before interrupt(),
            // including this emit, on every resume).
            case 'interrupt': {
                if (seenInterruptIds.current.has(event.interrupt_id)) break;
                seenInterruptIds.current.add(event.interrupt_id);
                setPendingInterrupt({ kind: event.kind, interruptId: event.interrupt_id, payload: event.payload || {} });
                setNodeStatus(prev => ({ ...prev, human_gate: 'running' }));
                appendLog(
                    event.kind === 'missing_information'
                        ? 'Taslak eksik bilgi içeriyor; kullanıcıdan girdi bekleniyor.'
                        : 'Taslak insan onayı bekliyor.'
                );
                setChatMessages(prev => [...prev, {
                    sender: 'assistant',
                    text: event.kind === 'missing_information'
                        ? 'Taslağı tamamlamak için birkaç bilgiye daha ihtiyacım var. Aşağıdaki formu doldurun.'
                        : 'Taslak hazır, ancak göndermeden önce onayınızı bekliyor.',
                    status: 'INTERRUPTED',
                }]);
                break;
            }

            case 'final_result':
                setStreamingText('');
                setChatMessages(prev => [...prev, {
                    sender: 'assistant',
                    text: event.reply,
                    status: event.workflow_status,
                    logs: currentLogsRef.current,
                    details: event.details
                }]);
                setActiveNode(null);
                break;

            case 'error':
                appendLog(`HATA: ${event.message}`);
                setChatMessages(prev => [...prev, {
                    sender: 'assistant',
                    text: `Hata oluştu: ${event.message}`,
                    status: 'FAILED',
                    logs: currentLogsRef.current,
                }]);
                setActiveNode(null);
                break;
        }
    };

    const handleDraftFormSubmit = async () => {
        if (!selectedDoc || !fullAnalysis) return;
        setDraftSubmitting(true);
        setDraftResult(null);
        try {
            const res = await fetch('/api/v1/documents/draft', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    storage_path: selectedDoc.storage_path,
                    classification: {
                        document_type: fullAnalysis.document_type,
                        document_type_label: fullAnalysis.document_type_label,
                        summary: fullAnalysis.summary,
                        fields: fullAnalysis.fields,
                        missing_fields: fullAnalysis.missing_fields,
                        mevzuat_references: fullAnalysis.mevzuat_references,
                    },
                    instructions: draftInstructions,
                    correspondence_type: draftCorrespondenceType || null,
                    reasoning_level: draftReasoningLevel,
                }),
            });
            const json = await res.json();
            if (res.ok && json?.data) {
                setDraftResult(json.data);
            } else {
                setDraftResult({ error: json?.error?.message || 'Taslak oluşturulamadı.' });
            }
        } catch (e) {
            console.error('Draft submission failed', e);
            setDraftResult({ error: 'Sunucuyla bağlantı hatası oluştu.' });
        } finally {
            setDraftSubmitting(false);
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
        (doc.summary || '').toLowerCase().includes(searchQuery.toLowerCase())
    );

    const renderFieldValue = (key: keyof EvrakFields, value: any) => {
        if (value === null || value === undefined || value === '') return '—';
        if (Array.isArray(value)) return value.length ? value.join(', ') : '—';
        return String(value);
    };

    return (
        <div className="dashboard-container">
            {/* LEFT SIDEBAR: File Upload & File List */}
            <div className="sidebar">
                <div className="logo-section">
                    <Activity size={24} style={{ color: '#06b6d4' }} />
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
                        <Clock size={14} style={{ color: '#6b7280' }} />
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

                {/* Görev 1 full-analysis panel for the selected document */}
                {selectedDoc && fullAnalysis && (
                    <div className="doc-list-section" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                        <div className="doc-list-header">
                            <h2>Evrak Analizi</h2>
                            <FileText size={14} style={{ color: '#6b7280' }} />
                        </div>
                        <div className="doc-scroll-area" style={{ padding: '4px 12px 12px 12px', fontSize: '11px', color: '#d1d5db' }}>
                            {fullAnalysis.extraction?.used_ocr && (
                                <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#f59e0b', marginBottom: 8 }}>
                                    <AlertTriangle size={12} />
                                    <span>OCR ile okundu; alanları doğrulayın.</span>
                                </div>
                            )}
                            {(fullAnalysis.extraction?.scrubbed_markers || []).length > 0 && (
                                <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#f59e0b', marginBottom: 8 }}>
                                    <AlertTriangle size={12} />
                                    <span>Olası talimat enjeksiyonu temizlendi.</span>
                                </div>
                            )}

                            <div style={{ fontWeight: 600, color: '#fff', marginBottom: 4 }}>Üst Veri Alanları</div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 8px', marginBottom: 10 }}>
                                {(Object.keys(EVRAK_FIELD_LABELS) as (keyof EvrakFields)[]).map(key => (
                                    <React.Fragment key={key}>
                                        <div style={{ color: '#6b7280' }}>{EVRAK_FIELD_LABELS[key]}</div>
                                        <div>{renderFieldValue(key, fullAnalysis.fields?.[key])}</div>
                                    </React.Fragment>
                                ))}
                            </div>

                            <div style={{ fontWeight: 600, color: '#fff', marginBottom: 4 }}>
                                Eksik Bilgiler ({fullAnalysis.missing_fields?.length || 0})
                            </div>
                            {(fullAnalysis.missing_fields || []).length === 0 ? (
                                <div style={{ color: '#10b981', marginBottom: 10 }}>Zorunlu alanların tümü mevcut.</div>
                            ) : (
                                <div style={{ marginBottom: 10 }}>
                                    {fullAnalysis.missing_fields.map((f, i) => (
                                        <div key={i} style={{ marginBottom: 4 }}>
                                            <span style={{ color: f.severity === 'zorunlu' ? '#ef4444' : '#f59e0b' }}>●</span>{' '}
                                            <strong>{f.label}</strong> ({f.severity}) — {f.mevzuat}
                                        </div>
                                    ))}
                                </div>
                            )}

                            <div style={{ fontWeight: 600, color: '#fff', marginBottom: 4 }}>
                                Mevzuat Önerileri ({fullAnalysis.mevzuat_references?.length || 0})
                            </div>
                            {(fullAnalysis.mevzuat_references || []).length === 0 ? (
                                <div style={{ color: '#6b7280', marginBottom: 10 }}>Öneri bulunamadı.</div>
                            ) : (
                                <div style={{ marginBottom: 10 }}>
                                    {fullAnalysis.mevzuat_references.map((m, i) => (
                                        <div key={i} style={{ marginBottom: 4 }}>
                                            <strong>{m.mevzuat}</strong>: {m.aciklama}
                                        </div>
                                    ))}
                                </div>
                            )}

                            <button
                                className="copy-btn"
                                style={{ width: '100%', justifyContent: 'center' }}
                                onClick={() => { setDraftFormOpen(true); setDraftResult(null); }}
                            >
                                <FilePlus size={12} />
                                Bu Evraktan Taslak Hazırla
                            </button>
                        </div>
                    </div>
                )}
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

                    {/* Görev 2: standalone drafting form (POST /documents/draft) */}
                    {draftFormOpen && selectedDoc && fullAnalysis && (
                        <div className="details-container" style={{ margin: '12px 16px 0 16px' }}>
                            <div className="details-title">Resmî Yazı Taslağı Oluştur</div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                <label style={{ fontSize: '11px', color: '#9ca3af' }}>Yazışma Türü</label>
                                <select
                                    value={draftCorrespondenceType}
                                    onChange={e => setDraftCorrespondenceType(e.target.value)}
                                    style={{ background: 'var(--bg-secondary)', color: '#fff', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '6px 8px' }}
                                >
                                    <option value="">Otomatik belirle</option>
                                    {correspondenceTypes.map((t: any) => (
                                        <option key={t.value} value={t.value}>{t.label}</option>
                                    ))}
                                </select>
                                <label style={{ fontSize: '11px', color: '#9ca3af' }}>Düşünme Seviyesi</label>
                                <select
                                    value={draftReasoningLevel}
                                    onChange={e => setDraftReasoningLevel(e.target.value as ReasoningLevel)}
                                    style={{ background: 'var(--bg-secondary)', color: '#fff', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '6px 8px' }}
                                >
                                    {REASONING_LEVELS.map(level => (
                                        <option key={level.value} value={level.value}>{level.label}</option>
                                    ))}
                                </select>
                                <label style={{ fontSize: '11px', color: '#9ca3af' }}>Talimatlar (opsiyonel)</label>
                                <textarea
                                    value={draftInstructions}
                                    onChange={e => setDraftInstructions(e.target.value)}
                                    placeholder="Örn: Talebi olumlu karşıla, ek süre 15 gün olsun."
                                    style={{ minHeight: 60, background: 'var(--bg-secondary)', color: '#fff', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '6px 8px', fontFamily: 'inherit' }}
                                />
                                <div style={{ display: 'flex', gap: 8 }}>
                                    <button className="copy-btn" onClick={handleDraftFormSubmit} disabled={draftSubmitting}>
                                        {draftSubmitting ? 'Oluşturuluyor...' : 'Taslak Oluştur'}
                                    </button>
                                    <button className="copy-btn" style={{ background: 'transparent' }} onClick={() => setDraftFormOpen(false)}>
                                        Kapat
                                    </button>
                                </div>

                                {draftResult && (
                                    draftResult.error ? (
                                        <div style={{ color: '#ef4444', fontSize: '12px' }}>{draftResult.error}</div>
                                    ) : (
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                            {(draftResult.missing_information || []).length > 0 && (
                                                <div style={{ color: '#f59e0b', fontSize: '12px' }}>
                                                    Taslak eksik bilgi içeriyor: {draftResult.missing_information.map((q: InfoQuestion) => q.label).join(', ')}.
                                                    Tamamlamak için sohbet üzerinden "taslak hazırla" diyerek devam edin.
                                                </div>
                                            )}
                                            <div className="details-grid">
                                                <div className="details-label">Güven Skoru:</div>
                                                <div className="details-value">%{Math.round(draftResult.confidence_score ?? 0)}</div>
                                                <div className="details-label">İnsan Onayı:</div>
                                                <div className="details-value">{draftResult.requires_human_approval ? 'Gerekli' : 'Gerekmiyor'}</div>
                                                <div className="details-label">Önerilen Birim:</div>
                                                <div className="details-value">{draftResult.destination || 'Belirlenmedi'}</div>
                                            </div>
                                            <div className="draft-box">{draftResult.draft}</div>
                                            <button className="copy-btn" onClick={() => copyToClipboard(draftResult.draft)}>
                                                <Copy size={12} />
                                                {copiedText ? 'Kopyalandı!' : 'Metni Kopyala'}
                                            </button>
                                        </div>
                                    )
                                )}
                            </div>
                        </div>
                    )}

                    {/* Human-in-the-loop resume form */}
                    {pendingInterrupt && (
                        <div className="details-container" style={{ margin: '12px 16px 0 16px', borderColor: 'rgba(245, 158, 11, 0.4)' }}>
                            <div className="details-title" style={{ color: '#f59e0b' }}>
                                {pendingInterrupt.kind === 'missing_information' ? 'Eksik Bilgi Talebi' : 'Taslak Onayı Bekleniyor'}
                            </div>

                            {pendingInterrupt.payload.draft && (
                                <div className="draft-box" style={{ marginBottom: 8 }}>{pendingInterrupt.payload.draft}</div>
                            )}

                            {pendingInterrupt.kind === 'missing_information' ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                    {(pendingInterrupt.payload.questions || []).map(q => (
                                        <div key={q.key}>
                                            <label style={{ fontSize: '11px', color: '#9ca3af', display: 'block' }}>
                                                {q.label} {q.why ? `— ${q.why}` : ''}
                                            </label>
                                            <input
                                                type="text"
                                                placeholder={q.example || ''}
                                                value={resumeAnswers[q.key] || ''}
                                                onChange={e => setResumeAnswers(prev => ({ ...prev, [q.key]: e.target.value }))}
                                                style={{ width: '100%', background: 'var(--bg-secondary)', color: '#fff', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '6px 8px' }}
                                            />
                                        </div>
                                    ))}
                                    <button className="copy-btn" onClick={() => handleResumeSubmit('answer')} disabled={loading}>
                                        Bilgileri Gönder ve Devam Et
                                    </button>
                                </div>
                            ) : (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                    <div className="details-grid">
                                        <div className="details-label">Güven Skoru:</div>
                                        <div className="details-value">%{Math.round(pendingInterrupt.payload.combined_score ?? 0)}</div>
                                    </div>
                                    <textarea
                                        placeholder="Revizyon talep ediyorsanız talimatınızı buraya yazın..."
                                        value={resumeInstructions}
                                        onChange={e => setResumeInstructions(e.target.value)}
                                        style={{ minHeight: 50, background: 'var(--bg-secondary)', color: '#fff', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '6px 8px', fontFamily: 'inherit' }}
                                    />
                                    <div style={{ display: 'flex', gap: 8 }}>
                                        <button className="copy-btn" onClick={() => handleResumeSubmit('approve')} disabled={loading}>Onayla</button>
                                        <button className="copy-btn" onClick={() => handleResumeSubmit('revise')} disabled={loading}>Revizyon İste</button>
                                        <button className="copy-btn" style={{ background: 'rgba(239,68,68,0.15)' }} onClick={() => handleResumeSubmit('reject')} disabled={loading}>Reddet</button>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

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
                                {msg.sender === 'assistant' && msg.logs && msg.logs.length > 0 && (
                                    <details style={{ marginTop: 8, fontSize: '11px', color: '#6b7280' }}>
                                        <summary style={{ cursor: 'pointer' }}>Akış günlüğü ({msg.logs.length})</summary>
                                        <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 2 }}>
                                            {msg.logs.map((l, i) => (
                                                <div key={i}><span style={{ opacity: 0.6 }}>[{l.time}]</span> {l.text}</div>
                                            ))}
                                        </div>
                                    </details>
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
                            <select
                                value={reasoningLevel}
                                onChange={e => setReasoningLevel(e.target.value as ReasoningLevel)}
                                title="Düşünme seviyesi: hız/kalite tercihi"
                                style={{ background: 'var(--bg-secondary)', color: '#fff', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '4px 8px', fontSize: '12px' }}
                            >
                                {REASONING_LEVELS.map(level => (
                                    <option key={level.value} value={level.value}>{level.label}</option>
                                ))}
                            </select>
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
                        <p>Deterministik yönlendirme, paralel evrak analizi, hibrit kalite kapılı taslak üretimi ve insan onayı.</p>
                    </div>

                    <div className="visualizer-scroll">

                        {/* SVG Visual Graph */}
                        <div className="graph-container">
                            <svg width="100%" viewBox="0 0 480 440" preserveAspectRatio="xMidYMid meet">
                                {/* Edges, drawn from the same node/edge tables as
                                    the circles so the two cannot drift apart. */}
                                {graphEdges.map((edge, i) => {
                                    const a = initialNodes.find(n => n.id === edge.from)!;
                                    const b = initialNodes.find(n => n.id === edge.to)!;
                                    const status = nodeStatus[edge.to] || 'todo';
                                    if (edge.back && status === 'skipped') return null;
                                    return (
                                        <line
                                            key={i}
                                            x1={a.x} y1={a.y}
                                            x2={b.x} y2={b.y}
                                            className={`link-line ${status}`}
                                            strokeDasharray={edge.parallel || edge.back ? '4 3' : undefined}
                                            opacity={edge.back ? 0.6 : undefined}
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

                                    const meta = nodeMeta[node.id];

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
                                                r={24}
                                                style={{
                                                    stroke,
                                                    strokeWidth: isActive ? 4 : 2,
                                                    opacity: currentStatus === 'skipped' ? 0.4 : 1,
                                                }}
                                            />
                                            <text
                                                x={node.x} y={node.y + 3}
                                                textAnchor="middle"
                                                style={{ fill: '#ffffff', fontSize: '8px', fontWeight: 600 }}
                                            >
                                                {node.short}
                                            </text>
                                            <text
                                                x={node.x} y={node.y + 38}
                                                textAnchor="middle"
                                                style={{
                                                    fill: currentStatus === 'skipped' ? '#4b5563' : '#9ca3af',
                                                    fontSize: '9.5px',
                                                    fontWeight: 500,
                                                }}
                                            >
                                                {node.label}{meta?.attempt > 1 ? ` (#${meta.attempt})` : ''}{meta?.reasoning_level && meta.reasoning_level !== 'balanced' ? ` [${meta.reasoning_level}]` : ''}
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
                                        {selectedDetailNode === 'verify' && 'Deterministik Kaynak Doğrulama'}
                                        {selectedDetailNode === 'judge' && 'Kalite Yargıcı Değerlendirmesi'}
                                        {selectedDetailNode === 'revise' && 'Revizyon Hazırlığı'}
                                        {selectedDetailNode === 'human_gate' && 'İnsan Onayı / Eksik Bilgi'}
                                        {selectedDetailNode === 'routing' && 'Birim Sevk Detayları'}
                                        {selectedDetailNode === 'assist' && 'Asistan Detayları'}
                                    </div>
                                    <span className={`status-badge ${nodeStatus[selectedDetailNode] || 'todo'}`}>
                                        {nodeStatus[selectedDetailNode] === 'running' ? 'Çalışıyor' :
                                            nodeStatus[selectedDetailNode] === 'completed' ? 'Tamamlandı' :
                                                nodeStatus[selectedDetailNode] === 'failed' ? 'Hata' :
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
                                                    <div className="details-label">Deterministik Skor:</div>
                                                    <div
                                                        className="details-value"
                                                        style={{ fontWeight: 600, color: (nodeResults.verify?.confidence_score ?? nodeResults.draft?.confidence_score ?? 0) >= 70 ? '#10b981' : '#f59e0b' }}
                                                    >
                                                        %{(nodeResults.verify?.verification?.confidence_score ?? nodeResults.draft?.verification?.confidence_score ?? 0).toFixed(0)}
                                                    </div>
                                                    <div className="details-label">Birleşik Skor:</div>
                                                    <div className="details-value" style={{ fontWeight: 600 }}>
                                                        %{(nodeResults.verify?.combined_score ?? nodeResults.draft?.combined_score ?? 0).toFixed(0)}
                                                    </div>
                                                    <div className="details-label">İnsan Onayı:</div>
                                                    <div className="details-value">
                                                        {(nodeResults.verify?.requires_human_approval ?? nodeResults.draft?.requires_human_approval) ? 'Gerekli' : 'Gerekmiyor'}
                                                    </div>
                                                    <div className="details-label">Yer Tutucu:</div>
                                                    <div className="details-value">
                                                        {nodeResults.verify?.verification?.placeholder_count ?? nodeResults.draft?.verification?.placeholder_count ?? 0} adet
                                                    </div>
                                                </div>
                                                <div className="details-label" style={{ marginTop: 4 }}>Doğrulanamayan İfadeler:</div>
                                                <div className="draft-box" style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#d1d5db' }}>
                                                    {((nodeResults.verify?.verification?.unsupported_claims ?? nodeResults.draft?.verification?.unsupported_claims) || []).length > 0
                                                        ? (nodeResults.verify?.verification?.unsupported_claims ?? nodeResults.draft?.verification?.unsupported_claims)
                                                            .map((c: any) => `• [${c.kind}] "${c.value}"`)
                                                            .join('\n')
                                                        : 'Taslaktaki tüm somut bilgiler kaynakla eşleşti.'}
                                                </div>
                                                {((nodeResults.verify?.verification?.missing_structure ?? nodeResults.draft?.verification?.missing_structure) || []).length > 0 && (
                                                    <>
                                                        <div className="details-label">Eksik Yapısal Unsurlar:</div>
                                                        <div className="draft-box" style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#f59e0b' }}>
                                                            {(nodeResults.verify?.verification?.missing_structure ?? nodeResults.draft?.verification?.missing_structure).join(', ')}
                                                        </div>
                                                    </>
                                                )}
                                            </div>
                                        )}

                                        {selectedDetailNode === 'judge' && (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                {nodeResults.judge?.rationale ? (
                                                    <>
                                                        <div className="details-grid">
                                                            <div className="details-label">Yargıç Skoru:</div>
                                                            <div className="details-value" style={{ fontWeight: 600 }}>%{(nodeResults.judge.score ?? 0).toFixed(0)}</div>
                                                            <div className="details-label">Talebi Karşılıyor mu:</div>
                                                            <div className="details-value">{nodeResults.judge.addresses_request ? 'Evet' : 'Hayır'}</div>
                                                            <div className="details-label">Resmî Üslup:</div>
                                                            <div className="details-value">{nodeResults.judge.register_ok ? 'Uygun' : 'Uygun Değil'}</div>
                                                            <div className="details-label">Kapanış Yönü:</div>
                                                            <div className="details-value">{nodeResults.judge.closing_direction} {nodeResults.judge.closing_correct ? '(doğru)' : '(kontrol edin)'}</div>
                                                        </div>
                                                        <div className="details-label">Gerekçe:</div>
                                                        <div className="draft-box" style={{ fontFamily: 'var(--font-sans)', fontSize: '11px' }}>{nodeResults.judge.rationale}</div>
                                                        {(nodeResults.judge.findings || []).length > 0 && (
                                                            <>
                                                                <div className="details-label">Bulgular:</div>
                                                                <div className="draft-box" style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#f59e0b' }}>
                                                                    {nodeResults.judge.findings.map((f: any) => `• [${f.severity}] ${f.detail} → ${f.suggested_fix}`).join('\n')}
                                                                </div>
                                                            </>
                                                        )}
                                                    </>
                                                ) : (
                                                    <div style={{ color: '#9ca3af', fontSize: '12px' }}>Yargıç kullanılamadı; deterministik doğrulama sonucuna göre karar verildi.</div>
                                                )}
                                            </div>
                                        )}

                                        {selectedDetailNode === 'revise' && (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                <div className="details-label">Tespit Edilen Kusurlar:</div>
                                                <div className="draft-box" style={{ fontFamily: 'var(--font-sans)', fontSize: '11px' }}>
                                                    {(nodeResults.revise?.repair_items || []).length > 0
                                                        ? nodeResults.revise.repair_items.map((r: any) => `• [${r.kind}] ${r.detail}${r.suggested_fix ? ` → ${r.suggested_fix}` : ''}`).join('\n')
                                                        : 'Kusur listesi boş.'}
                                                </div>
                                            </div>
                                        )}

                                        {selectedDetailNode === 'human_gate' && (
                                            <div style={{ color: '#d1d5db', fontSize: '12px' }}>
                                                {pendingInterrupt
                                                    ? 'İnsan yanıtı bekleniyor — yukarıdaki formu doldurun.'
                                                    : 'İnsan onayı/eksik bilgi adımı tamamlandı.'}
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
                                                {nodeResults.classification.fields && (Object.keys(EVRAK_FIELD_LABELS) as (keyof EvrakFields)[]).map(key => (
                                                    <React.Fragment key={key}>
                                                        <div className="details-label">{EVRAK_FIELD_LABELS[key]}:</div>
                                                        <div className="details-value">{renderFieldValue(key, nodeResults.classification.fields[key])}</div>
                                                    </React.Fragment>
                                                ))}
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
                                                    <div className="details-label">Deneme Sayısı:</div>
                                                    <div className="details-value">{nodeResults.draft.attempts || '1'} deneme</div>
                                                </div>

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

                                                {nodeResults.draft.evaluation_notes && (
                                                    <div style={{ marginTop: 4 }}>
                                                        <div className="details-label" style={{ color: '#10b981', display: 'flex', alignItems: 'center', gap: 4 }}>
                                                            <CheckCircle size={12} />
                                                            Doğrulama/Yargıç Notları:
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

                                        {selectedDetailNode === 'assist' && (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                <div className="details-grid">
                                                    <div className="details-label">Durum:</div>
                                                    <div className="details-value">{nodeResults.assist.status || 'Tamamlandı'}</div>
                                                </div>
                                                {toolCalls.length > 0 && (
                                                    <>
                                                        <div className="details-label">Kullanılan Araçlar:</div>
                                                        <div className="draft-box" style={{ fontFamily: 'var(--font-sans)', fontSize: '11px' }}>
                                                            {toolCalls.map((call, idx) => (
                                                                <div key={idx}>
                                                                    [{call.time}] {call.tool}
                                                                    {Object.keys(call.args).length > 0 ? `(${JSON.stringify(call.args)})` : '()'}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </>
                                                )}
                                                <div className="details-label">Cevap:</div>
                                                <div className="draft-box" style={{ fontFamily: 'var(--font-sans)' }}>
                                                    {nodeResults.assist.reply || 'Cevap bulunamadı.'}
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
                                            {selectedDetailNode === 'draft' && 'Taslak Oluşturma: Brief ve mevzuat bağlamını kullanarak resmî Türkçe taslağı token token üretir. Doğrulama başarısız olursa Revizyon → Taslak döngüsü en fazla bir kez tekrarlanır.'}
                                            {selectedDetailNode === 'verify' && 'Deterministik Doğrulama: Taslaktaki her sayı, tarih, kurum, tutar ve mevzuat atfının kaynak evrakta veya getirilen mevzuatta geçip geçmediğini denetler. Model çağrısı içermez.'}
                                            {selectedDetailNode === 'judge' && 'Kalite Yargıcı: Hızlı katman modeliyle talebe uygunluk, resmî üslup, kapanış yönü (arz/rica) ve muhatap tutarlılığını değerlendirir — regex\'in yakalayamadığı muhakeme gerektiren kontroller.'}
                                            {selectedDetailNode === 'revise' && 'Revizyon Hazırlığı: Doğrulama ve yargıç tarafından tespit edilen kusurları numaralı bir listeye dönüştürür; LLM çağrısı içermez. Ardından Revizyon Ajanı yalnızca listelenen kusurları düzeltir.'}
                                            {selectedDetailNode === 'human_gate' && 'İnsan Onayı Kapısı: Taslak eksik bilgi içeriyorsa veya güven skoru düşükse akışı durdurur ve bir insandan girdi/onay bekler. LangGraph checkpointer sayesinde bu bekleme kalıcıdır.'}
                                            {selectedDetailNode === 'routing' && 'Birim Sevki: Hazırlanan taslağın hangi alt birime sevk edileceğini gerekçesiyle belirler. Güven skoru düşükse doğrudan insan onayına yönlendirir.'}
                                            {selectedDetailNode === 'assist' && 'Asistan: Kullanıcıyla sohbet eder ve gerektiğinde (belge içeriği veya mevzuat hakkında bir soru olduğunda) kendi kararıyla ilgili aracı çağırarak yanıtını zenginleştirir.'}
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
