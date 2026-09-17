export const MOCK_RAG_RESPONSE_CHUNKS = [
  JSON.stringify({ protocol_version: 2, sequence: 1, type: 'start' }) + '\n',
  JSON.stringify({
    protocol_version: 2,
    sequence: 2,
    type: 'token',
    payload: { token: 'Chào mừng bạn đến với Trường Đại học Công Thương TP.HCM (HUIT)!\n\n' },
  }) + '\n',
  JSON.stringify({
    protocol_version: 2,
    sequence: 3,
    type: 'token',
    payload: { token: 'Dưới đây là bảng thông tin tuyển sinh và học phí dự kiến năm 2026:\n\n' },
  }) + '\n',
  JSON.stringify({
    protocol_version: 2,
    sequence: 4,
    type: 'token',
    payload: {
      token: '| Mã ngành | Tên ngành | Chỉ tiêu 2026 | Học phí dự kiến (triệu/năm) |\n| :--- | :--- | :--- | :--- |\n| 7480201 | Công nghệ thông tin | 350 | 32 - 36 |\n| 7480101 | Khoa học máy tính | 200 | 32 - 36 |\n| 7340101 | Quản trị kinh doanh | 450 | 28 - 32 |\n| 7540101 | Công nghệ thực phẩm | 400 | 28 - 32 |\n\n',
    },
  }) + '\n',
  JSON.stringify({
    protocol_version: 2,
    sequence: 5,
    type: 'token',
    payload: { token: 'Thông tin chi tiết được công bố trên cổng thông tin chính thức của Nhà trường.' },
  }) + '\n',
  JSON.stringify({
    protocol_version: 2,
    sequence: 6,
    type: 'sources',
    payload: {
      sources: [
        {
          i: 1,
          title: 'Đề án tuyển sinh HUIT 2026',
          url: 'https://huit.edu.vn/tuyen-sinh-2026',
          text: 'Quy chế và đề án tuyển sinh chính thức năm 2026 của HUIT.',
        },
        {
          i: 2,
          title: 'Bảng biểu phí sinh viên HUIT',
          url: 'https://huit.edu.vn/hoc-phi-2026',
          text: 'Chi tiết học phí các nhóm ngành kinh tế và kỹ thuật.',
        },
      ],
    },
  }) + '\n',
  JSON.stringify({
    protocol_version: 2,
    sequence: 7,
    type: 'artifact',
    payload: {
      artifact_id: 'art-test-1',
      type: 'chart',
      title: 'Biểu đồ Tuyển sinh & Học phí HUIT 2026',
      preview_url: '/mock-chart.svg',
      manifest_url: '/mock-manifest.json',
      available_formats: ['svg', 'png', 'pdf', 'xlsx', 'docx'],
      status: 'ready',
    },
  }) + '\n',
  JSON.stringify({ protocol_version: 2, sequence: 8, type: 'text_completed' }) + '\n',
  JSON.stringify({ protocol_version: 2, sequence: 9, type: 'completed' }) + '\n',
];

export const MOCK_ADMIN_HEALTH = {
  status: 'healthy',
  version: '2.0.0-staging',
  uptime_seconds: 86400,
  memory: {
    total_mb: 16384,
    used_mb: 4120,
    percent: 25.1,
  },
  cpu_percent: 12.5,
  disk: {
    total_gb: 512,
    used_gb: 128,
    percent: 25.0,
  },
  database: {
    status: 'connected',
    pool_size: 10,
    active_connections: 2,
  },
  redis: {
    status: 'connected',
    ping_ms: 1.2,
  },
};

export const MOCK_ADMIN_JOBS = [
  {
    job_id: 'job-101',
    type: 'export_xlsx',
    status: 'completed',
    created_at: '2026-09-17T08:00:00Z',
    progress: 100,
    metadata: { filename: 'bang-hoc-phi-2026.xlsx', total_rows: 39 },
  },
  {
    job_id: 'job-102',
    type: 'upscale_image',
    status: 'running',
    created_at: '2026-09-17T08:30:00Z',
    progress: 65,
    metadata: { scale_factor: 2, target_format: 'png' },
  },
  {
    job_id: 'job-103',
    type: 'export_pdf',
    status: 'failed',
    created_at: '2026-09-17T08:45:00Z',
    progress: 40,
    error: 'Renderer timeout after 30s',
    metadata: { filename: 'de-an-2026.pdf' },
  },
];
