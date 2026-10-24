# Public Hook Facade (`frontend/hooks`)

Thư mục này là **Public Hook Facade** nằm ngay tại thư mục gốc của `frontend`, giúp bất kỳ kỹ sư nào mở dự án cũng nhìn thấy ngay toàn bộ giao diện tương tác (Hook API) công khai của hệ thống giao diện.

---

## 1. Mục đích của Public Hook Facade

- **Điểm chạm thống nhất (Single Entry Point)**: Cho phép các tầng cấp cao như `App.tsx`, layout toàn cục, hoặc các module ngoài feature truy cập các Hook cần thiết một cách trực quan qua alias `@hooks`:
  ```ts
  import {
    useChatStream,
    useSessionBootstrap,
    useArtifactWorkflow,
  } from '@hooks';
  ```
- **Bảo vệ ranh giới kiến trúc (Encapsulation)**: Ngăn chặn việc các module bên ngoài xâm nhập sâu vào cấu trúc file nội bộ của từng feature.
- **Tránh trùng lặp logic**: `frontend/hooks` **chỉ re-export**, không chứa bất kỳ bản sao implementation nào.

---

## 2. Vị trí Implementation Thật

Toàn bộ mã thực thi (logic, state nội bộ, hiệu ứng React) **100% nằm trong `src/`**:

| Module Facade | Vị trí Implementation Thật |
| :--- | :--- |
| `hooks/chat.ts` | `src/features/chat/hooks/useChatStream.ts`<br>`src/features/chat/hooks/useConversation.ts` |
| `hooks/session.ts` | `src/features/session/hooks/useSessionBootstrap.ts` |
| `hooks/artifacts.ts` | `src/features/artifacts/hooks/useArtifactWorkflow.ts`<br>`src/features/artifacts/hooks/useArtifactExport.ts`<br>`src/features/artifacts/hooks/useArtifactUpscale.ts`<br>`src/features/artifacts/hooks/useArtifactActions.ts` |
| `hooks/admin.ts` | `src/features/admin/hooks/useAdminAuth.ts`<br>`src/features/admin/hooks/useAdminDashboard.ts`<br>`src/features/admin/hooks/useAdminOps.ts` |
| `hooks/voice.ts` | `src/features/voice/hooks/useSpeechRecognition.ts`<br>`src/features/voice/hooks/useSpeechSynthesis.ts` |
| `hooks/common.ts` | `src/shared/hooks/useDebounce.ts`<br>`src/shared/hooks/useLocalStorage.ts`<br>`src/features/theme/hooks/useTheme.ts`<br>`src/features/history/hooks/useChatHistory.ts`<br>`src/features/admission-visuals/hooks/useVisualLightbox.ts` |

---

## 3. Phân định Hook Public vs Hook Internal

### Hook Public (Được phép re-export qua Facade)
- Các Hook phục vụ quy trình làm việc cốt lõi của ứng dụng (`useChatStream`, `useConversation`, `useSessionBootstrap`, `useArtifactWorkflow`, `useAdminAuth`, ...).
- Các Hook tiện ích dùng chung (`useDebounce`, `useLocalStorage`, `useTheme`, `useChatHistory`, `useVisualLightbox`).

### Hook Internal (Tuyệt đối KHÔNG re-export ra Facade)
- **`useImageGeneration`** (`src/features/image-generation/hooks/useImageGeneration.ts`):
  - *Lý do*: Hook này chỉ phục vụ riêng màn hình dialog của `ImageGenerationModal.tsx`, gắn chặt với state nội bộ của modal và chưa có Canonical JSON Schema độc lập được kiểm duyệt cho public contracts.

---

## 4. Quy tắc Nghiêm ngặt cho Facade

Các file trong thư mục `frontend/hooks/`:

1. **CHỈ ĐƯỢC**:
   - `import` và `re-export` Hook public từ `src/features/...` hoặc `src/shared/...`.
   - `export type` bắt nguồn từ contracts chuẩn hóa hoặc kiểu dữ liệu đầu ra của Hook.
2. **TUYỆT ĐỐI CẤM**:
   - Gọi `fetch`, `axios`, hoặc `httpClient`.
   - Khai báo API endpoint hoặc URL string `/api/...`.
   - Chứa logic nghiệp vụ (business logic) hay tính toán dữ liệu.
   - Định nghĩa state React (`useState`, `useEffect`, `useReducer`).
   - Chứa component React (JSX/TSX).
   - Chứa secret, token, hay cấu hình môi trường.
   - Tạo implementation trùng lặp với file trong `src/`.

---

## 5. Quy tắc Import Nội bộ Feature

- **Trong cùng một Feature**: Bắt buộc import trực tiếp từ đường dẫn tương đối nội bộ (ví dụ: `import { useConversation } from '../hooks/useConversation'`). **Không đi vòng qua `@hooks`** để tránh tạo phụ thuộc vòng (dependency cycle).
- **Từ ngoài Feature hoặc App**: Sử dụng alias `@hooks` (ví dụ trong `App.tsx`).

---

## 6. Mối quan hệ giữa Hook và JSON Schema Contract Core

Mọi Hook trong hệ thống đều tuân thủ chặt chẽ luồng phụ thuộc đơn hướng bắt nguồn từ `backend/json_schemas`:

$$\text{Human-reviewed JSON Schema (backend/json\_schemas/)}$$
$$\downarrow$$
$$\text{Backend API / Stream Models \& MongoDB Validators}$$
$$\downarrow$$
$$\text{Frontend Canonical Schemas (src/shared/contracts/schemas/)}$$
$$\downarrow$$
$$\text{Runtime Type Guards \& Assertions (src/shared/contracts/index.ts)}$$
$$\downarrow$$
$$\text{Feature API (src/features/*/api)}$$
$$\downarrow$$
$$\text{Feature Hook Implementation (src/features/*/hooks)}$$
$$\downarrow$$
$$\text{Public Hook Facade (frontend/hooks/)}$$
$$\downarrow$$
$$\text{App \& Presentation Components (src/app/App.tsx, components)}$$

Khi backend thay đổi hợp đồng dữ liệu:
1. Sửa và bump version tại `backend/json_schemas/`.
2. Chạy `python scripts/sync_json_schemas.py` để cập nhật bản sao frontend.
3. Chạy `npm test` và `pytest` để kiểm tra độ tương thích.

---

## 7. Cách thêm Hook Public mới

1. Viết mã implementation và unit test đầy đủ trong `src/features/<feature-name>/hooks/use<HookName>.ts`.
2. Đảm bảo Hook không gọi trực tiếp `fetch` (phải gọi qua tầng `src/features/<feature-name>/api/`).
3. Đảm bảo API payload đã có hoặc tuân theo JSON Schema trong `backend/json_schemas`.
4. Mở file nhóm tương ứng trong `frontend/hooks/<module>.ts` (hoặc tạo file mới nếu là feature lớn mới).
5. Thêm lệnh re-export:
   ```ts
   export { useNewHook, type UseNewHookReturn } from '../src/features/<feature-name>/hooks/useNewHook';
   ```
6. Nếu tạo file nhóm mới, re-export trong `frontend/hooks/index.ts`.
7. Cập nhật unit test trong `frontend/tests/publicHookFacade.test.ts`.
