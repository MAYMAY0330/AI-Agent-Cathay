# 國泰金融控股股份有限公司暨各子公司大數據Hadoop平台管理要點



<!-- page:1 route:text -->

## Page 1

【使用權限與管理作業要點 2021/06/22 版本】 
1 
 國泰金融控股股份有限公司暨各子公司大數據Hadoop 平台管理要點 
110 年06 月22 日訂定 
權責單位：數據生態發展部 數據科技科 
 
第一條 （訂定目的及法律依據） 
為規範本公司暨各子公司（以下稱「本集團」或「本集團各公司」）「大數據
Hadoop 平台」(以下簡稱 Hadoop 平台)之數據儲存、處理、傳輸及利用等管理
機制之完整性、安全性及可用性，並有效管理及維護其正常運作，爰訂定本要
點。 
 
第二條 （適用對象） 
本公司及依《金融控股公司法》所定義之本公司使用Hadoop 平台，應依本要點
之規定辦理，惟如各該公司就Hadoop 維護管理事項訂有更高控管強度之規定
者，另應從其規定。 
 
第三條 （Hadoop 平台相關說明） 
一、叢集  
係指將多臺一般商用等級的伺服器或虛擬機組合成分散式的運算和儲存叢
集，包含管理節點、資料節點、探索節點、營運節點等伺服器角色，透過分散式
架構的HDFS 檔案系統、搭配可分散運算的程式演算方法，提供巨量資料的儲存
和處理能力。 
Hadoop 平台分為兩個叢集: 大數據分析平台（Hadoop Analysis 
Platform，HAP）及大數據資料湖（Hadoop DataLake，HDL）。 
(一)大數據分析平台 
大數據分析平台（以下稱「HAP 叢集」）係為提供業務使用者作為數據
探索環境使用之平台，個人資料需經「資料加密」處理、「資料偽裝」
遮蔽或經演算法亂碼處理後始得放入此平台，並限於此平台正式環境使
用。 
(二)大數據資料湖 
大數據資料湖（以下稱「HDL 叢集」）係為提供Hadoop 平台營運服務作
業之叢集，此叢集僅限正式環境可存放明碼資料，但禁止建置業務使用
者帳號。 
二、Hadoop 相關服務 
(一)HDFS 檔案系統 
HDFS (Hadoop Distributed File System)係指一種被設計成適合運行
在通用硬體上的分佈式檔案系統。 
(二)Yarn 計算資源管理系統 
Yarn (Yet Another Resource Negotiator)係指一個計算資源管理系
統，用來管理各種分散式運算應用程式所使用的CPU 與記憶體資源。 
(三)Hive 資料庫 
謝豐嶽   2026-05-26 14:11:38.68


<!-- page:2 route:text -->

## Page 2

【使用權限與管理作業要點 2021/06/22 版本】 
2 
Hive 資料庫是基於HDFS 檔案系統的一個資料庫工具，可以將結構化或
非結構化的資料檔案對應為結構化資料表，並提供簡單的sql 查詢功
能。 
 
三、伺服器角色 
(一)管理節點 (Master Node) 
作為主從式架構中的主要節點角色，提供Hadoop 平台相關服務的管理
功能。 
(二)資料節點 (Worker Node) 
作為主從式架構中的從屬節點角色，提供Hadoop 平台相關服務的儲存
運算功能。 
(三)探索節點 (eXplore Node) 
係為HAP 叢集內提供業務使用者作數據探索所需各項數據服務，包含但
不限於以下作業:程式帳號用於運行應用程序、服務帳號建置叢集管理
工具或業務使用者以命令列介面進行數據探索的叢集伺服器。 
(四)營運節點 (Edge Node) 
係為HDL 叢集內提供數據生產作業所需各項數據服務，包含但不限於以
下作業:程式帳號用於運行應用程序、服務帳號建置叢集管理工具的叢
集伺服器。 
 
第四條 （Hadoop 平台使用者/管理者角色與權責） 
一、業務使用者 
係指依本要點第八條第一項取得授權之人員。 
二、系統管理者 
係指依本要點第六條取得授權之人員，角色包含infra 管理者、叢集管理
者、帳號權限管理者、平台管理者、排程管理者及工程管理者。 
(一)infra 管理者 
係指負責Hadoop 平台所屬相關資訊基礎建設管理及維運之人。 
infra 管理者權責如下： 
1. 新增叢集節點作業相關事宜。 
2. 定期進行伺服器上作業系統層帳號清查作業相關事宜。 
3. 定期進行網路防火牆清查作業相關事宜。 
4. 管理機房容量作業相關事宜，包括但不限於機櫃空間、網路設備、
電力容量管理。 
5. 維運及管理資訊基礎建設作業相關事宜。 
(二)叢集管理者 
係指負責Hadoop 平台所屬HDFS、YARN 及Hive 資料庫管理維運之
人。 
叢集管理者權責如下： 
1. 負責HDFS 服務根目錄暨權限建置相關事宜。 
謝豐嶽   2026-05-26 14:11:38.68


<!-- page:3 route:text -->

## Page 3

【使用權限與管理作業要點 2021/06/22 版本】 
3 
2. 負責HDFS、YARN 服務容量管理作業相關事宜。 
3. 負責Hadoop 平台HDFS 服務的維運管理相關事宜。 
4. 負責Hive 資料庫新增、修改、刪除與權限設定相關事宜。 
(三)帳號權限管理者 
係指負責Hadoop 平台帳號、群組新增、修改及刪除之人。 
帳號權限管理者權責如下： 
1. 負責Hadoop 平台帳號、群組的新增、修改與刪除作業相關事宜。 
2. 負責提供內稽內控所需帳號權限清查作業相關資料及辦理相關事
宜。 
(四)平台管理者 
係指負責設定Hadoop 平台上探索節點、營運節點與HDFS 目錄權限管理
作業、帳號權限申請審核作業及配合業務管理單位進行帳號權限清查作
業之人。 
平台管理者權責如下： 
1. 負責專用探索節點、營運節點伺服器目錄權限規劃與設定作業相關
事宜。 
2. 負責專用HDFS 檔案系統根目錄權限規劃與設定作業相關事宜。 
3. 負責審查帳號、群組異動作業相關事宜。 
4. 負責配合業務管理單位定期進行帳號權限清查作業，並留存稽核軌
跡。 
5. 負責專用範圍內的維運管理作業相關事宜。 
(五)排程管理者 
係指負責Hadoop 平台資料蒐集、處理之批次排程相關開發、維運作業
之人。 
排程管理者權責如下： 
1. 確認每日批次排程作業正確性。 
2. 開發、管理及維運批次排程作業相關事宜。 
3. 負責排程帳號與執行密碼變更作業。 
(六)工程管理者 
係指負責Hadoop 平台上資料應用之演算法、數據工程相關開發、維運
作業之人。 
工程管理者權責如下： 
1. 每日確認工程作業正確性。 
2. 工程開發、管理、維運作業相關事宜。 
3. 負責工程帳號與執行密碼變更作業 
 
第五條 （Hadoop 平台帳號類型及帳號管理） 
一、業務使用者帳號: 係指業務使用者使用之Hadoop 平台帳號。 
二、特殊權限帳號： 
係指具有特殊使用目的或高存取權限之帳號，含服務帳號、應用程式帳號及
謝豐嶽   2026-05-26 14:11:38.68


<!-- page:4 route:text -->

## Page 4

【使用權限與管理作業要點 2021/06/22 版本】 
4 
各公司Hadoop 平台最高權限帳號。 
(一)服務帳號:係指提供Hadoop 平台的各項大數據服務功能使用之帳號，
如:GUI 介面查詢AD 權限帳號。 
(二)應用程式帳號: 係指建置於Hadoop 平台上的各項系統所使用之帳號，
如: ETL 排程帳號。 
(三)各公司Hadoop 平台最高權限帳號:係指各公司之平台管理者帳號，此帳
號之保管者，具有控管所屬公司HDFS 根目錄與專用伺服器根目錄之權
限，惟禁止存取非該公司之資料。 
 
三、帳號管理 
(一)業務使用者帳號與密碼應避免與他人共用。如因系統限制而有多人共用
同一帳號之情形，應訂定其它控制機制，如記錄連線來源位址、設簿登
記、密碼變更等。 
(二)特殊權限帳號應訂定其它控制機制，如記錄登入來源位址、限制該帳號
僅供系統使用不得供人員使用等。 
(三)特殊權限帳號應進行帳號納管作業，若有特殊需求得將密碼分為A/B 
組，分由兩人持有，並以靜態密碼函保管，密碼持有人於拆封靜態密碼
函後之隔日需變更密碼，變更後之密碼得不設密碼到期日，惟保管人須
每年檢視密碼保管情況，並於必要時於服務維護時間進行密碼變更。 
(四)Hadoop 平台禁止第三方服務廠商申請帳號。 
(五)特殊權限帳號之申請，若係為Hadoop 平台管理維護相關事項，限定由
管理維護單位依《國泰金融控股股份有限公司資訊作業申請管理要點》
要點》
及其所屬公司相關帳號申請規定(如有)申請；若係為各公司Hadoop 平
台作業需求，限定由各公司Hadoop 平台資訊管理單位依《國泰金融控
融控
股股份有限公司資訊作業申請管理要點》申請。
要點》申請。 
 
第六條 （Hadoop 平台管理單位/使用單位與權責劃分） 
Hadoop 平台以本公司數據生態發展部為「業務管理單位」，以所有使用公司共同
指定之單位為「管理維護單位」，各使用公司並應自行指定「Hadoop 平台資訊管理單
位」。各該管理單位/使用單位權責如下： 
一、業務管理單位： 
負責訂定及修訂管理要點、規劃資訊架構(包括但不限於軟硬體配置設計、
成本管控及高可用性與效能評估作業等)、跨公司資料流傳遞架構及軟硬體
採購相關事項、定期發起帳號清查作業。 
業務管理單位規劃Hadoop 平台所連結之帳號系統，帳號權限管理者由該系
統維護單位科級主管指定同仁擔任。 
二、管理維護單位： 
負責Hadoop 平台之維運管理事項(包括但不限於硬體採購、作業系統、資料
庫、弱點掃描及Hadoop 相關服務所需軟硬體的相關作業等) 。 
管理維護單位科級主管應指定科內同仁擔任infra 管理者與叢集管理者。 
謝豐嶽   2026-05-26 14:11:38.68


<!-- page:5 route:text -->

## Page 5

【使用權限與管理作業要點 2021/06/22 版本】 
5 
三、各公司Hadoop 平台資訊管理單位： 
負責所屬Hadoop 平台之作業流程規劃、資料流架構規畫及帳號管理，並擔
任內稽內控窗口，且須依管理維護單位提供之弱點掃描結果進行弱點修補作
業、並須配合業務管理單位進行定期執行帳號清查作業。 
各公司Hadoop 平台資訊管理單位科級主管應指定科內同仁擔任平台管理
者、排程管理者與工程管理者。 
四、各公司Hadoop 平台業務使用單位： 
係指被授權於Hadoop 平台上進行數據分析探索之業務單位，需將本要點所
列相關事宜納入內部稽核項目定期查核。 
 
第七條 （Hadoop 平台安全管理） 
各公司Hadoop 平台相關作業應符合所屬公司及管理維護單位所屬公司之資訊安
全政策。 
管理維護單位應指定獨立安全之環境妥善放置Hadoop 平台相關設備，並建置安
全管理機制，以保障服務正常運作，另應建立定期儲存與備份機制。 
Hadoop 平台安全管理措施應包含但不限於以下事項: 
一、本集團各公司資料需存放於不同資料庫及目錄上隔離，各公司資料僅限各公
司業務使用者分析使用，禁止非該公司人員存取。 
二、管理節點與資料節點因Hadoop 特性為集團共用伺服器，探索節點與營運節
點各公司需使用各公司專屬伺服器或虛擬機，禁止混用。 
三、各公司專用Hive 資料庫、HDFS 目錄異動的作業程序限各公司Hadoop 平台
資訊管理單位依本公司《國泰金融控股股份有限公司資訊作業申請管理要
點》之規定提出申請，審核通過後交由管理維護單位指定之叢集管理員負責
建置。 
四、Hadoop 平台作業系統應定期檢視是否有重大弱點之修正程式並視需要予以
更新。 
五、Hadoop 平台需有獨立防火牆設定，所有連線皆需提出申請核准後始得開通
防火牆連線。 
六、系統開發技術標準、基礎設施技術標準、系統架構標準、系統資訊安全標準
詳如附件二。 
 
第八條 （Hadoop 平台使用權限管理） 
各公司Hadoop 平台業務使用單位人員得因業務需要依各公司Hadoop 平台資訊管
理單位之規定，檢附【Hadoop 平台帳號權限申請表】(詳附件一) 及本人簽署之保密
切結書經業務使用單位科級主管(或代理人)核准後，依《國泰金融控股股份有限公司
資訊作業申請管理要點》之規定向各該公司Hadoop 平台資訊管理單位申請業務使用
者帳號及權限。申請核准並留存相關紀錄後，Hadoop 平台帳號權限管理者應以集團
員工編號加上公司縮寫為帳號命名原則，進行Hadoop 平台帳號權限建置；業務使用
單位人員僅限申請任職或兼任公司之帳號，惟於申請兼任公司之帳號時，應於該兼任
公司依前述程序提出申請。 
謝豐嶽   2026-05-26 14:11:38.68


<!-- page:6 route:text -->

## Page 6

【使用權限與管理作業要點 2021/06/22 版本】 
6 
各公司Hadoop 平台資訊管理單位應配合業務管理單位通知，每季檢核各公司業
務使用單位業務使用者名單及權限，業務使用單位並應隨時視業務需要，評估人員權
限之妥適性，並列入自行查核項目，如有業務使用者離職或調動，業務使用單位應於
正式生效前，依《國泰金融控股股份有限公司資訊作業申請管理要點》之規定向其
Hadoop 平台資訊管理單位申請刪除該員之帳號及權限。 
業務使用者基於執行職務之必要連結Hadoop 平台時，正式環境與測試環境僅限
由VDI 連接，且不得經由Internet 接入VDI 存取資料，如需下載資料，需經業務使
用單位部室主管及資料所屬公司同意，並依資料所屬公司之資料下載規定辦理。業務
使用單位部室主管並應禁止業務使用者透過公司郵件、USB、外部網頁郵件、雲端硬
碟或其他任何方式攜出資料。 
 
第九條 （Hadoop 平台資料匯入及匯出之管理） 
業務使用者擬匯入資料至Hadoop 平台，或自Hadoop 平台匯出資料時，應依本公
司《國泰金融控股股份有限公司資訊作業申請管理要點》
要點》及《國泰金融控股股份有限
公司資訊傳輸管理要點》之規定，會辦相關單位，並經核准後方得辦理。 
為有效保護資料安全，匯入資料應進行適當之偽裝程序後，始可轉入Hadoop 平台。
應偽裝欄位包含所有個人資料，各公司Hadoop 平台資訊管理單位可依資料重要性，增
加偽裝欄位。匯入資料應依照與資料倉儲平台一致的加密規則進行偽裝，以維資料安
全與ㄧ致性。 
 
第十條 （Hadoop 平台程式管理） 
各公司Hadoop 平台資訊管理單位之開發人員就維運作業所涉之相關程式，應於開
發環境進行開發，並依各公司相關規定辦理程式之部署上線。 
 
第十一條 
（Hadoop 平台保密規定） 
Hadoop 平台相關人員於接觸或使用資料時，不可有洩漏或移作他用之情事，並需
依相關規定使用Hadoop 平台，平台相關人員所屬單位之科級主管負有控管資料之責
任，並應責成相關人員簽署保密切結書並嚴守保密義務。 
 
第十二條 
（Hadoop 平台資料銷毀之安全要求） 
Hadoop 平台相關人員就其所取得之Hadoop 平台資料之銷毀，應遵守下列規定： 
一、含有個人資料之紙本文件與表單，禁止回收再利用，應確實辦理銷毀作業。 
二、相關人員所屬單位應依法令或業務需要，就其人員所取得之Hadoop 平台資料
訂定處理或利用期限，並應規劃適當之存放方式，以確保資料之可用性。 
三、相關人員所屬單位就其人員所取得Hadoop 平台資料，如已屆處理或利用期限，
應確實辦理銷毀作業。 
 
第十三條 
（Hadoop 平台跨公司資料傳遞方式） 
業務使用者申請於Hadoop 平台之資料傳輸作業，僅限於金控與子公司間進行，並
以Hadoop 平台提供之Hive 資料庫及HDFS 目錄範圍內之資料為限，且應依據《國泰金
融控股股份有限公司暨各子公司間資料傳輸作業管理辦法》及《國泰金融控股股份有
融控股股份有
限公司資訊作業申請管理要點》之規定
要點》之規定提出申請並執行；相關申請核准後，得依Hive
資料庫及HDFS 檔案型式於獨立的公司對公司資料交付區進行資料傳輸作業；各公司
Hadoop 平台資訊管理單位應保留資料傳輸軌跡，以利進行傳檔紀錄檢核。 
謝豐嶽   2026-05-26 14:11:38.68


<!-- page:7 route:text -->

## Page 7

【使用權限與管理作業要點 2021/06/22 版本】 
7 
Hadoop 平台上公司間資料傳輸作業使用之Hive 資料庫、HDFS 目錄，限由資料所
有公司之Hadoop 平台資訊管理單位依《國泰金融控股股份有限公司資訊作業申請管理
要點》之規定提出申請，經金控資訊處審核後交由管理維護單位指定之叢集管理員負
責建置。 
第一項資料傳輸作業之相關資料傳輸限制如下: 
一、金控傳輸至子公司:限子公司業務使用者提出申請，傳輸作業限由本公司
Hadoop 平台資訊管理單位於相關申請核准後執行，傳遞資料類型僅限網路上
公開資料與依集團共用目的受各子公司委託採購的外購資料。 
二、子公司傳輸至金控:限本公司業務使用者提出申請，傳輸作業限由各子公司
Hadoop 平台資訊管理單位於相關申請核准後執行，傳遞資料類型僅限經核准
之客戶分析資料。
。 
Hadoop 平台禁止子公司間之資料傳輸作業，此類作業需另依《國泰金融控股
股份有限公司暨各子公司間資料傳輸作業管理辦法》辦理。 
 
第十四條 
（內部控制與內部稽核） 
本公司及各子公司使用及管理Hadoop 平台之相關單位，應將本要點所列事宜納入
單位內部控制制度，定期辦理自行查核。 
 
第十五條 
（未盡事宜） 
本要點未盡事宜，悉依相關法令及本公司相關規定辦理。 
 
第十六條 
（訂定、修正、廢止及施行） 
本要點經總經理核定後實施，修正或廢止時亦同。 
謝豐嶽   2026-05-26 14:11:38.68


<!-- page:8 route:text -->

## Page 8

【國泰金控大數據 Hadoop 平台帳號權限申請表 2021/06/18 版本】 
 
國泰金控大數據 Hadoop 平台帳號權限申請表 
申請人員公司：               申請人員部門：               申請人員科別：                     
申請人員姓名：               申請人員電話：               申請日期：                         
請勾選權限異動類型： 
帳號異動清單 
(請提供使用人員姓名、集團員編) 
(系統帳號請提供帳號名、功能別) 
權限異動 
類型 
帳號類型 
帳號類型/功能 
 
□新增 
□業務使用者 
□業務使用者 
 
係指對所屬公司資料有分析需求之各公司
編制內業務單位人員。 
□系統管理者 
□叢集管理者 
 
係指負責Hadoop 平台所屬HDFS、YARN 及
Hive 資料庫管理維運同仁。 
□平台管理者 
 
係指負責設定Hadoop 平台上探索節點、營
運節點與HDFS 目錄權限管理作業、帳號權
限申請審核作業及配合業務管理單位進行
帳號權限清查作業同仁。 
□排程管理者 
 
係指負責Hadoop 平台資料蒐集、處理之批
次排程相關開發、維運作業同仁。 
□工程管理者 
 
係指負責Hadoop 平台上資料應用之演算
法、數據工程相關開發、維運作業同仁。 
□程式帳號 
□程式帳號 
 
係指建置於Hadoop 平台上的各項排程與工
程系統所使用之帳號 
□異動 
異動作業說明： 
 
 
□刪除/離職 
刪除作業說明： 
 
 
□其他 
其他作業說明： 
 
 
申請單位簽章 
申請單位主管：                      申請人員：                       
設定需求備註 
 
 
註一:申請者與使用者為不同人員時，請取得使用者的簽章同意 
 
謝豐嶽   2026-05-26 14:11:38.68


<!-- page:9 route:text -->

## Page 9

(附件二) 
系統開發技術標準 
Technology Standards of System Development 
Item 
Standard 
Version 
Exception 
Client-Side / Front-End 
Application 
Browser 
HTML 
CSS 
JavaScript 
jQuery 
Bootstrap 
Vue.js 
Angular 
HTML5 
CSS3 
Based on browser 
3.1.1 or above 
3 or above 
2.5.16 
8 or above 
ActiveX, 
jQuery 1.12.4 (IE 6,7,8) 
jQuery 2.2.4 (IE 9 or above) 
Semantic 2.0.0 or above 
Kendo 3 or above 
Desktop 
Java 
C#.NET 
Java SE 8 or above 
.Net Framework 4.0 or above 
Java SE 7 
C, C++ 
Server-Side / Business 
/ Middleware Service 
& Application 
Presentation Layer / 
Web Server / Web Site 
JSF 
Spring 
Node.js 
Cub-ebaf 
ASP.NET 
ASP.NET Core MVC 
Java EE 7 or above 
4.3.3 or above 
6.7.0 or above 
1.1.0 or above 
.Net Framework 4.0 or above 
.Net Core 2.0 or above 
JSP 
PHP 
Service / Business 
Layer 
EJB 
Spring 
Cub-ebaf 
Spring Boot 
Java 
C#.NET 
C#.NET Core 
Java EE 7 or above 
4.3.3 or above 
1.1.0 or above 
2.0.2 or above 
Java SE 8 or above 
.Net Framework 4.0 or above 
.Net Core 2.0 or above 
C, C++, Python 
Golang 1.8 
Spring Boot 1.5.x 
 
Data Access / 
Persistence Layer 
JPA 
Hibernate 
ADO.NET 
 
Spring Data [module] 
Cub-ebaf 
Java EE 7 or above 
5.2.2 or above 
.Net Framework 4.0 or 
above、.Net Core 2.0 or above 
1.x or above 
1.1.0 or above 
JDBC 
Client Access(ODBC), Entity 
Framework(6.0 or above) 
iSeries Access(ODBC) 
MyBatis (3.4.1 or avove) 
Analysis / Reporting / Big Data Application 
Hadoop  
Spark 
R 
Python 
2.0 or above 
2.0 or above 
3.3.1 or above 
3.5.2 or above 
MS SQL (SSRS) 
Java 8,7 
Spark 1.6 
Python 2.7 
Scala (2.11.8 or above) 
ETL Tool / Job Flow 
Control-M 
Pentaho Kettle 
Informatica 
 
7.1 or above 
MS SQL (SSIS) 
ETL Automation 
Service 
謝豐嶽   2026-05-26 14:11:38.68


<!-- page:10 route:text -->

## Page 10

DataStage 11.x (IBM 
InfoSphere DataStage) 
Oozie (Hadoop , job 
flow) 4.2.0 or above 
Java Runtime Environment 
Open JDK 
1.8 or above 
Oracle JDK, IBM JDK 
基礎設施技術標準 
Technology Standards of Infrastructure 
Item 
Standard 
Version 
Exception 
Operation System 
Windows Server 
Red Hat Enterprise Linux 
2019 or above 
7 or above 
AIX (System P, RS/6000) 
i/OS (System i, AS/400) 
z/OS (Z System, mainframe) 
CentOS 
Application Server / Web Server / 
Middleware 
IIS 
Apache HTTP 
JBoss EAP 
FUSE 
Apache Kafka 
Apache Tomcat 
9 or above 
2.4 or above 
7 or above 
8 or above 
0.10 or above 
8 or above 
IBM MQ 
WAS 
RabbitMQ 
Oracle GlassFish Server 4.0 or above 
Camel 
ActiveMQ 
Database Server 
Oracle 
MSSQL 
Redis 
Hadoop 
MongoDB 
19c or above 
2016 or above 
4.0.9 or above 
DB2 
PostgreSQL 
mariadb 5.5 or above 
Hypervisor 
Hyper-V 
vSphere 
3.0 R2 or above 
6.7 or above 
 
Hardware base 
x86 
 
RS/6000 
AS/400 
Mainframe 
Container 
Docker 
17.09 or above 
 
Container orchestrator 
OCP 
3.11 or above 
Kubernetes 
OKD 
3.11 or above 
Kubernetes 
Maintenance Support 
If the system's BIA Level is within 1~3, the maintenance support (included open source) is 
required. 
 
 
 
 
 
 
 
 
謝豐嶽   2026-05-26 14:11:38.68


<!-- page:11 route:text -->

## Page 11

系統架構標準 
System Architecture Standards 
Item 
Standard 
Exception 
Service Architecture 
Microservice Architecture 
Traditional Web Service (SOA) 
Service Type 
RESTful based web service 
SOAP based web service 
Message format 
JSON 
XML 
系統資訊安全標準 
System Information Security Standards 
Item 
Standard 
Exception 
Confidentiality 
(Encryption 
Algorithm) 
Symmetric 
Encryption 
AES (256 bit) or stronger 
3DES with triple keys 
3DES with double keys 
Asymmetric 
Encryption 
RSA (2048 bit or higher) or stronger 
 
Integrity 
Hash Algorithm 
SHA 2 family or stronger 
SHA1, MD5 
Availability 
(BIA level 1~3 
system 
redundancy 
standard) 
Onsite 
Redundancy 
AA Mode, AS Mode or off line backup 
machines 
 
Offsite/Remote 
Redundancy 
AA Mode, AS Mode or off line backup 
machines 
 
RTO (Recovery 
Time Objective) 
BIA level 1 : 4 hr 
BIA level 2 : 6 hr 
BIA level 3 : 24 hr 
 
Authentication 
1. AD Kerberos / LDAP authentication 
mechanisms  
2. Multi-factor authentication  
3. CUB security control system 
 
Authorization 
1. Authorization mechanisms supporting 
RBAC (Role Based Access Control)  
2. OAuth 2.0 authorization mechanism 
OAuth 1.0 authorization mechanism 
Accounting (Logging) 
Any Logging/audit trails should have following 
elements:  
-Who, What, When, Where, How 
Proprietary logging mechanisms by 
IBM Mainframe & AS/400 or other 
legacy systems 
Wireless Security (For internal 
network) 
1. WPA2-Enterprise  
2. 802.11i 
 
Data / File 
Transfer Security 
Web Transfer 
Protocol 
HTTPS (TLS 1.2 or stronger) 
 
General Transfer 
Protocol 
SFTP or FTPS or stronger (e.g. Connect-Direct) 
 
Encryption Tool / Server 
PGP  
GPG (Open Source)  
HSM (FIPS 140-2 Level 3 or higher) 
 
謝豐嶽   2026-05-26 14:11:38.68
