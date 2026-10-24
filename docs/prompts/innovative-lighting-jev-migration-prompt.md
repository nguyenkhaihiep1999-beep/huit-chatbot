# Prompt triển khai Jev hướng 2 và chuyển kho tri thức sang Innovative Lighting Đồng Nai

Bạn đang làm việc trong dự án `D:\chatbot2`. Hãy thực hiện thay đổi dưới đây đến khi có kết quả kiểm chứng được, không chỉ lập kế hoạch. Đọc AGENTS.md áp dụng nếu có; kiểm tra trạng thái Git và bảo toàn các thay đổi có sẵn. Không được báo thành công bằng kết quả mock cho một bước cần xác minh trên hệ thống thật.

## Mục tiêu và phạm vi đã được người dùng chọn

- Công ty mục tiêu: Innovative Lighting Technologies tại Đồng Nai, website `https://innovativelightingco.com/`.
- Luồng mặc định cho bộ dữ liệu công ty: người dùng → retrieval MongoDB (tìm chính xác/keyword/vector) → Jev đánh giá minh chứng → policy ứng dụng → Qwen/LLM diễn đạt tiếng Việt và trích dẫn → phản hồi chatbot.
- Giữ nguyên khả năng dùng hướng 1: người dùng → Jev phân loại ý định → retrieval MongoDB → LLM. Không xóa module, provider, contract, test hoặc khả năng bật lại hướng này theo bộ dữ liệu sau này.
- Khi cần, có thể bật kết hợp hai bước Jev; không buộc mọi yêu cầu phải gọi Jev hai lần.
- Giữ kiến trúc FastAPI, React, MongoDB, cache, NDJSON v2, gateway dữ liệu, worker, quản trị, xác thực và các chức năng chung đang có. Chỉ thay lớp cấu hình/nghiệp vụ và dữ liệu cần thiết; không viết lại hệ thống hoặc chuyển nền tảng.
- Chuyển toàn bộ KHO TRI THỨC ĐANG PHỤC VỤ chatbot sang dữ liệu ILT đã kiểm duyệt. Không diễn giải thành xóa mọi collection MongoDB. Không xóa tài khoản, phiên, lịch sử chat, jobs, artifacts, audit hoặc dữ liệu vận hành không thuộc phạm vi.
- HUIT phải có đúng một tệp backup `.bak` tự chứa, đủ phục hồi dữ liệu và profile HUIT. Được giữ thêm kho HUIT không hoạt động để rollback nhanh; không cần xóa nó để chứng minh chuyển đổi thành công.
- Thứ tự bắt buộc: kiểm tra hiện trạng → hoàn thiện/kiểm thử bước Jev thứ 2 → sao lưu và thử phục hồi HUIT → thu thập dữ liệu ILT → chuẩn hóa, embedding và phân cụm → nghiệm thu → chuyển profile phục vụ sang ILT. Không bắt đầu crawl/import ILT trước khi hoàn tất bước Jev thứ 2 và kiểm chứng backup.

## Những điều đã quan sát được, phải kiểm tra lại trên checkout hiện tại

1. `backend/app/rag/pipeline.py` đã có `decide_intent_sync` trước retrieval và `decide_evidence_sufficiency_sync` sau retrieval. Không tạo một tích hợp Jev thứ hai trùng chức năng; audit và hoàn thiện wiring hiện có.
2. `backend/.env` khi khảo sát có `JEV_MODE=assist`. Điều này chỉ chứng minh cấu hình tệp local, không chứng minh môi trường tiến trình đang chạy/deployment hoặc API thật thành công. Không in secret khi kiểm tra.
3. `rag/reranker.py` hiện lấy kết quả vector rồi mới gọi `get_top_cluster`; `cluster_boost` là cộng điểm sau truy xuất. Đây chưa phải cluster pre-filter giúp thu hẹp phạm vi vector search.
4. `data_access/registered_operations/rag_operations_v2.py` đang hardcode `huit_kb`, `huit_vector_index`; projection và `RetrievedDocumentItem` chưa giữ `cluster_id` và metadata sản phẩm. Chỉ đổi `MONGODB_COLL` không đủ.
5. `rag/embedding.py` cache `_cluster_centroids` ở cấp lớp và trỏ đến file HUIT. Phải tránh dùng nhầm centroids khi chuyển profile.
6. Dedup hiện có nơi dùng `(source_url, category)` hoặc chỉ URL; nhiều sản phẩm/trang trong cùng catalogue có thể bị gộp mất. Kiểm tra `candidate_id`, dedup retrieval và supplementary retrieval.
7. Jev evidence và LLM có thể nhận các excerpt dài khác nhau; có helper canonical bundle nhưng cần kiểm tra việc dùng thực sự ở cả hai phía. Không coi có helper là đã đồng bộ.
8. `scripts/backup_production.py` hiện dùng projection bỏ `_id`, không bao trọn cơ chế phục hồi; có thể vẫn đặt `COMPLETED` khi một collection lỗi. `rollback_production.py` chủ yếu kiểm tra sức khỏe, chưa phải chương trình restore dữ liệu hoàn chỉnh. Không dùng nguyên các script này để tuyên bố HUIT khôi phục được.
9. Prompt, intent, fallback, evidence policy, hình và tài liệu mẫu đang chứa nghiệp vụ HUIT. Giữ chúng trong profile HUIT; không để chúng xuất hiện khi ILT đang hoạt động.

## Giai đoạn 0 — Chốt hiện trạng và kế hoạch thay đổi tối thiểu

- Ghi nhận đường đi request thật từ route đến retrieval, Jev và generation; xác định backend/deployment/database đích từ cấu hình hiện có, không đoán từ tên thư mục.
- Phân biệt rõ: mã nguồn, cấu hình local, trạng thái live, test mock và kết quả đo live.
- Ghi baseline chức năng HUIT và cách phục hồi profile trước khi sửa. Chỉ đọc các collection cần thiết khi kiểm tra hiện trạng; không đưa dữ liệu riêng tư hoặc secret vào báo cáo.
- Đọc `docs/architecture/LTX_RULE_IMPLEMENTATION.md`, schema registry và các contract liên quan. Giữ chiều phụ thuộc hiện có.
- Dựng kế hoạch ngắn rồi bắt đầu triển khai. Không tạo commit chứa `.env`, URI có mật khẩu, API key, dữ liệu nhạy cảm hoặc tệp backup.

## Giai đoạn 1 — Hoàn thiện Jev sau retrieval, bảo toàn Jev trước retrieval

### Cấu hình và tương thích

- Có cấu hình độc lập cho hai tác vụ Jev theo profile: `intent` và `evidence`, mỗi tác vụ hỗ trợ `off`, `shadow`, `assist`. Tên cấu hình cụ thể theo quy ước dự án; ánh xạ tương thích với `JEV_MODE` cũ, không âm thầm đổi hành vi HUIT đang dùng.
- Profile ILT mặc định ưu tiên `evidence=assist`, `intent=off`; hướng 1 vẫn nguyên khả năng bật riêng hoặc kết hợp sau này. Profile HUIT giữ hành vi cũ cho đến khi có yêu cầu đổi.
- Profile được resolve phía server từ whitelist, chụp nhất quán cho toàn bộ request. Client/LLM/Jev không được truyền tùy ý collection, raw Mongo filter hoặc pipeline để vượt gateway.
- Tôn trọng tổng deadline; phân bổ ngân sách từng tác vụ khi bật cả hai. Timeout, hết quota, lỗi schema hoặc lỗi mạng không làm hỏng streaming; fallback có kiểm soát và ghi nhận đúng trạng thái.
- Không mặc định một ngưỡng confidence là bằng chứng độ chính xác. Không gọi thêm Jev khi đã có kết quả tương đương trong cùng request và tập minh chứng không thay đổi.

### Hành động sau khi Jev đánh giá

- `sufficient`: cho phép LLM trả lời từ minh chứng được duyệt.
- `partial`: chỉ trả lời phần có căn cứ; nêu cụ thể trường còn thiếu.
- `insufficient`: nếu có khả năng truy xuất tốt hơn, thử bổ sung tối đa một lượt trong deadline; nếu vẫn thiếu thì thông báo thiếu nguồn hoặc chuyển đầu mối phù hợp.
- `conflicting`: kiểm tra đúng model/biến thể/phiên bản/thị trường và nguồn hiệu lực; thử bổ sung có giới hạn, không tự chọn một con số thiếu căn cứ.
- Chỉ hỏi lại người dùng khi thiếu thông tin họ có thể bổ sung như mã hàng hoặc mục đích sử dụng. Không biến mọi trường hợp kho dữ liệu thiếu thông tin thành yêu cầu người dùng hỏi lại.
- `shadow` chỉ quan sát/ghi số đo, tuyệt đối không tác động routing, policy, retriever, prompt hoặc câu trả lời. Kiểm tra cả đường `policy_verdict`, không chỉ điều kiện `decision_applied`.
- Nếu retrieval rỗng: xử lý minh bạch, không lấy ngẫu nhiên vài tài liệu rồi coi là có căn cứ. Jev/LLM không được bịa nguồn.
- Dùng một evidence bundle đã chuẩn hóa và redacted để Jev xét đúng dữ kiện mà LLM sẽ dùng, với stable ID, URL, trang catalogue, SKU và phiên bản khi có. Nếu tài liệu bổ sung làm đổi bundle thì cập nhật đánh giá theo deadline hoặc dùng policy thận trọng; không tái dùng kết luận cũ như thể vẫn chính xác.
- Bảo toàn UTF-8 tiếng Việt, giới hạn payload và danh sách/count minh chứng nhất quán. Trích dẫn phải dẫn được đến đúng tài liệu/trang chứa dữ kiện.

### Kiểm chứng trước khi thu thập dữ liệu mới

- Thêm/chỉnh test có ý nghĩa cho intent-only, evidence-only, cả hai, off/shadow/assist, shadow không đổi đầu ra, timeout/quota/malformed, evidence rỗng/thiếu/mâu thuẫn, supplementary retrieval, và tính nhất quán bundle.
- Kiểm tra hướng 1 vẫn hoạt động với HUIT; event NDJSON v2, session và error/fallback vẫn đúng contract.
- Chạy bộ test liên quan; nếu kiểm tra được API thật bằng cấu hình hiện có thì chạy smoke nhỏ, có giới hạn và báo rõ kết quả. Không đánh đồng mock với live. Nếu thiếu khả năng kiểm tra live, hoàn thành phần độc lập và ghi giới hạn cụ thể.

## Giai đoạn 2 — Một tệp `.bak` HUIT có thể phục hồi thực sự

- Tạo artifact local `backups/huit-<timestamp>.bak`; dùng định dạng container/version rõ ràng như ZIP/TAR chứa BSON dump và manifest. Đuôi `.bak` không phải định dạng; cung cấp công cụ đọc/restore tương ứng.
- Tệp phải tự chứa: các collection tri thức HUIT và dữ liệu phụ thuộc cần thiết; đầy đủ `_id`, BSON type, embeddings, metadata; regular index, validator, Atlas Search/Vector Search definitions; scraped sources, centroids, profile HUIT, cấu hình không có secret và template/tài nguyên cần để bật lại HUIT. Liệt kê rõ phạm vi và phụ thuộc thực tế.
- Nếu tài liệu/ảnh cần thiết chỉ nằm trong object storage, sao lưu các blob thuộc HUIT được tham chiếu cùng mapping và checksum vào gói, hoặc giữ được snapshot tự chứa tương đương trong chính gói. Không báo tự chứa nếu chỉ lưu URL đến dữ liệu có thể biến mất.
- Không đóng gói credentials, `.env` nguyên bản, dữ liệu người dùng hay toàn bộ database ngoài phạm vi. Credential được cấp từ môi trường khi restore. Gói này không được public hoặc commit vào Git.
- Bảo đảm snapshot nhất quán: nếu có tiến trình cập nhật KB, dùng chiến lược snapshot/quiesce phù hợp có kiểm chứng. Manifest ghi thời điểm, phạm vi, schema/profile/model version, counts và SHA-256 từng payload. Có kiểm tra tính toàn vẹn toàn gói khi restore; không dùng checksum tự tham chiếu bất khả thi.
- Backup phải thất bại rõ ràng nếu bất kỳ thành phần bắt buộc nào lỗi/thiếu; không ghi `COMPLETED` khi chưa đủ.
- Cung cấp lệnh dry-run, backup, verify và restore có target chỉ định rõ, idempotent hoặc có kiểm soát xung đột. Restore mặc định không ghi đè dữ liệu đang phục vụ.
- Thử restore từ chính tệp `.bak` sang database/namespace kiểm thử tách biệt; so sánh `_id`, BSON types, counts, hashes và mẫu nội dung/vector. Phục hồi index/validator; Atlas index cần tạo lại từ definition và đợi queryable/READY, không giả vờ index đã nằm sẵn trong dump BSON.
- Chứng minh có thể bật lại profile HUIT và chạy một tập câu hỏi smoke. Dọn namespace kiểm thử theo cách an toàn sau khi giữ bằng chứng. Không thay dữ liệu đang phục vụ nếu backup/restore chưa đạt.

## Giai đoạn 3 — Thu thập và kiểm duyệt dữ liệu Innovative Lighting

- Nguồn chính thức bắt đầu tại `https://innovativelightingco.com/` và catalogue được website này liên kết: `https://online.fliphtml5.com/zpdsw/wjtd/`.
- Không trộn nguồn `innovativelight.com` của công ty tại Iowa, Mỹ. Chỉ mở rộng nguồn khi xác minh nó thuộc/liên kết chính thức với đúng ILT Đồng Nai.
- Thu thập toàn bộ nội dung công khai có liên quan và truy cập được: giới thiệu, liên hệ, năng lực sản xuất, OEM/ODM, nhóm sản phẩm, catalogue và datasheet/tài liệu tải xuống chính thức nếu có. Crawl lịch sự, có giới hạn, không vượt đăng nhập hoặc truy cập tài liệu nội bộ chưa được cấp.
- Catalogue từng được thấy có 135 trang theo trình xem; đó không phải số SKU, không phải 135 trang đã trích xuất. Kiểm tra số trang hiện tại, lập ledger theo trang: thành công, lỗi, thiếu dữ liệu, cần duyệt.
- Ưu tiên PDF/text gốc; nếu chỉ có ảnh thì OCR/bảng theo trang và kiểm tra trực quan. Giữ bản nguồn, source URL, trang, thời điểm thu thập, hash và trạng thái duyệt. Không tuyên bố thu thập đầy đủ nếu có trang/tài liệu chưa đọc được.
- Phân biệt dữ kiện công ty tự công bố, thông số model và chứng nhận có chứng từ. Không suy từ chứng nhận chung ra mọi SKU đều đạt cùng tiêu chuẩn.
- Không bịa hoặc suy ra giá, MOQ, tồn kho, thời gian giao, bảo hành, điện áp, lumen, CRI/CCT, dimming hoặc IP khi nguồn không nêu. Trường thiếu để null/unknown với policy thích hợp; đặc biệt phân biệt công suất tối đa của bóng với công suất thực tế của bộ đèn.
- Tài liệu chủ yếu tiếng Anh vẫn giữ nguyên bản để truy nguồn; chuẩn hóa tên/từ đồng nghĩa tiếng Việt cho retrieval. Không dịch hoặc thay đổi mã SKU, số liệu, đơn vị; bản dịch là dữ liệu dẫn xuất có nguồn gốc rõ ràng.
- Dữ liệu đưa vào bộ đang phục vụ phải được kiểm tra. Mã hàng và mọi ô thông số số học dùng để tư vấn phải đối chiếu trực tiếp với trang nguồn; phần chưa xác minh đưa vào quarantine, không để LLM trình bày như sự thật.
- Báo cáo độ phủ theo URL/trang/SKU; tách số thu thập, số đã kiểm duyệt, số được import, số lỗi và lý do. Không tự nhân bản/sinh dữ liệu để đạt chỉ tiêu.

## Giai đoạn 4 — Profile, MongoDB, embeddings và phân cụm phục vụ giảm độ trễ

### Dữ liệu và tích hợp kiến trúc

- Tạo profile ILT, collection tri thức có version và search index tương ứng; giữ MongoDB trong cùng kiến trúc. Không ghi đè kho HUIT hoặc đổi tên collection đang hoạt động trước khi nghiệm thu.
- Mỗi chunk có stable `chunk_id`, `document_id`, `dataset_id`, `dataset_version`, `source_url`, trang/section, hash, loại nội dung, verification status, model/SKU nếu có, embedding version/model và `cluster_id`. Sản phẩm/biến thể có identity độc lập.
- Sửa dedup theo chunk/product identity; cùng một catalogue URL phải giữ được nhiều trang, nhiều SKU, nhiều thuộc tính và các nguồn mâu thuẫn cần đối chiếu.
- Dùng model embedding đa ngôn ngữ hiện có nếu phù hợp, kiểm tra kích thước thực và prefix query/passage theo model. Tạo embeddings/centroids mới từ ILT; không dùng centroids HUIT. Không trộn vector từ model hoặc version khác nhau.
- Bổ sung schema có version, registry và migration dry-run. Contract mới cần giữ các metadata qua projection/Pydantic output; không lách `extra=forbid` bằng raw dict.
- Tuân thủ `route → service/use case → operation adapter → registered operation → guarded Mongo context`. Operation đổi contract phải tăng version và cập nhật pinned checksum/allowlist ở cả hai đầu; không sửa lén contract v2 đã phát hành hoặc truy cập Mongo trực tiếp từ pipeline.
- Cache gắn profile/dataset version, policy version, từng chế độ Jev, embedding/cluster version và model LLM thực dùng. Chuyển profile phải reload/invalidate centroids và metadata liên quan; không trả cache HUIT cho ILT. Giữ request đang xử lý nhất quán với profile đã chụp.

### Phân cụm thực sự tham gia truy xuất

- Triển khai chế độ phân cụm có thể bật/tắt theo profile. Fit offline trên embeddings ILT; chọn K theo kích thước/phân bố và benchmark, không coi nhãn sản phẩm thủ công là bằng chứng đã làm clustering vector.
- Lưu seed, K, model/dimension, normalization/metric, phiên bản dữ liệu, centroids và phân bố cụm. Xử lý corpus nhỏ, vector lỗi, cụm rỗng hoặc lệch; không ép phân cụm nếu không có lợi.
- Tính query embedding một lần; chọn một hoặc vài cụm gần nhất TRƯỚC khi gọi vector search. Cho phép tìm nhiều cụm, mở rộng hoặc tìm toàn cục khi định tuyến mơ hồ, thiếu kết quả hoặc câu hỏi so sánh xuyên nhóm.
- Đăng ký các trường cluster/dataset dùng lọc trong Atlas Vector Search index và truyền pre-filter vào `$vectorSearch` qua contract/gateway có whitelist; không chỉ `$match` sau vector search hoặc cộng điểm rerank rồi gọi là giảm phạm vi tìm.
- Tìm mã hàng chính xác bằng index SKU/alias trước hoặc song song theo chiến lược có giới hạn. Giữ keyword/hybrid fallback. Thiếu embedding, centroids, index chưa sẵn sàng hoặc routing lỗi phải fallback có kiểm soát và telemetry; không che lỗi hạ tầng như thể kho không có dữ liệu.
- Với dữ liệu riêng collection, namespace phải nhất quán; nếu có collection chung, mọi nhánh exact/keyword/vector/fallback/supplementary phải lọc đúng dataset/version phía server. Không để dữ liệu HUIT lọt qua nhánh dự phòng.
- Không hứa clustering chắc chắn nhanh hơn ANN toàn cục. Đo trên cùng corpus, cùng embedding, cùng ngân sách ứng viên và điều kiện cache; báo cả chi phí định tuyến, multi-cluster và global fallback. Tinh chỉnh `numCandidates` dựa trên chất lượng/độ trễ, không chỉ hạ để có số đẹp.

## Giai đoạn 5 — Nghiệm thu và chuyển ILT thành bộ dữ liệu đang phục vụ

- Giữ profile HUIT với prompt/heuristic/template riêng để phục hồi; ILT dùng intent nghiệp vụ sản phẩm, so sánh, thông số, OEM/ODM, yêu cầu báo giá, hỗ trợ và liên hệ. Gỡ HUIT khỏi luồng ILT, không xóa khả năng HUIT khỏi mã nguồn.
- Chỉnh tên bot, lời chào, câu hỏi gợi ý, thông tin liên hệ và tài liệu sinh tự động theo profile. Không để bảng học phí/điểm chuẩn/hotline trường trong ILT. Không tự nhận đã được công ty ủy quyền nếu chưa có căn cứ.
- Dùng Qwen nếu đã cấu hình hợp lệ; giữ provider fallback sẵn có. Không tự ý mua dịch vụ, đổi provider hoặc tuyên bố Qwen đang chạy chỉ vì tên nó xuất hiện trong trace.
- Lập bộ câu hỏi độc lập có đáp án/nguồn do người kiểm tra xác minh, gồm tra SKU, so sánh biến thể, yêu cầu tự nhiên tiếng Việt, câu hỏi tiếp nối, thiếu dữ kiện, dữ liệu không có, nhầm công ty, xuyên cụm và HUIT ngoài phạm vi ILT. Không dùng câu trả lời do chính chatbot sinh làm ground truth duy nhất.
- So sánh trên cùng bộ câu hỏi: không Jev, chỉ hướng 1, chỉ hướng 2, cả hai khi cần; riêng retrieval so sánh clustering on/off. Đo recall@k dựa trên nhãn, độ đúng thuộc tính/SKU, độ đúng trích dẫn, xử lý thiếu nguồn, retrieval p50/p95, TTFT, end-to-end p50/p95, lỗi/fallback và chi phí. Ghi rõ số mẫu, warm/cold cache, phần mock/offline/live và cấu hình đo; không tự đặt SLA rồi báo đạt.
- Chỉ bật cluster-filter cho chế độ mặc định nếu phép đo lặp lại cho thấy lợi ích độ trễ có ý nghĩa và không bỏ sót kết quả quan trọng. Mọi ca SKU chuẩn và so sánh quan trọng phải qua; nếu chưa đạt, tiếp tục tối ưu hoặc giữ clustering ở chế độ tắt/shadow để bảo toàn chất lượng, báo đúng điều kiện chưa đạt.
- Chạy test Jev/RAG mới, contract/schema checks, LTX, NDJSON, cache isolation, backup/restore, frontend test/lint/build nếu có sửa frontend. Sau các gate liên quan đạt, chạy bộ hồi quy backend/frontend của dự án; ghi đúng lệnh và kết quả.
- Import idempotent vào collection/version ILT chưa hoạt động, kiểm tra counts/hashes, embedding coverage, schema/index readiness, dữ liệu kiểm duyệt và truy vấn mẫu. Đừng coi insert thành công là index đã searchable.
- Trước cutover xác nhận tệp `.bak` đã thử restore, không có lỗi chặn và mọi request sẽ resolve được profile ILT nhất quán. Chuyển cấu hình phục vụ bằng cơ chế hiện có, không wipe database; xử lý cache/centroids và tiến trình cần reload.
- Người dùng đã yêu cầu chuyển kho tri thức sang ILT: sau khi đủ điều kiện, thực hiện cutover trong đúng môi trường đã xác định, không chỉ để lại kế hoạch hoặc đòi duyệt lại bước thường lệ. Không tự triển khai sang môi trường khác chưa xác định. Nếu thiếu quyền, credential hoặc nguồn bắt buộc thì dừng riêng bước phụ thuộc và báo blocker thật.
- Smoke sau chuyển: bot trả lời tiếng Việt về ILT với nguồn đúng; các câu hỏi giá/tồn kho thiếu dữ liệu được xử lý đúng; không trả HUIT từ fallback/cache; session, streaming và quản trị còn hoạt động. Có thể chuyển lại HUIT từ backup/profile theo runbook đã thử.

## Đầu ra bắt buộc

1. Code đã thay đổi và test tương ứng, giải thích ngắn tại sao vẫn bảo toàn hướng 1 và kiến trúc hiện có.
2. Một tệp `.bak` HUIT tự chứa; vị trí, định dạng, kích thước, trạng thái kiểm tra và bằng chứng restore. Runbook có lệnh thực tế để phục hồi HUIT mà không phải đoán tên collection/index hoặc tìm lại tài nguyên đã mất.
3. Dataset ILT nguồn/chuẩn hóa, ledger thu thập/kiểm duyệt, báo cáo import, quarantine và phiên bản đang hoạt động. Không commit raw data/backup nếu trái quy ước hoặc chứa dữ liệu cần giữ riêng.
4. Script ingestion, embedding, clustering, import, verify và profile switching có dry-run, chạy lại an toàn và hướng dẫn rõ.
5. Báo cáo chất lượng/độ trễ có số đo thật, tradeoff clustering và trạng thái hướng 1/hướng 2 theo profile; nêu rõ giới hạn chưa đo/không truy cập được.
6. Báo cáo cuối ghi chính xác: môi trường đã tác động, active profile, các thay đổi, tests, backup/restore, nguồn/độ phủ ILT, search mode và cách quay lại HUIT. Không ghi “hoàn tất toàn bộ” nếu còn bước bắt buộc bị chặn.

## Tài liệu tham chiếu

- `docs/architecture/LTX_RULE_IMPLEMENTATION.md` và schema/operation contracts trong repository là căn cứ tích hợp tại dự án.
- MongoDB Vector Search stage và pre-filter: https://www.mongodb.com/docs/vector-search/query/aggregation-stages/vector-search-stage/
- MongoDB Vector Search index definitions: https://www.mongodb.com/docs/vector-search/indexes/vector-search-type/
- Khi triển khai, đối chiếu đúng tính năng/version/tier của MongoDB đích; không sao chép cú pháp không tương thích từ tài liệu một sản phẩm khác.
