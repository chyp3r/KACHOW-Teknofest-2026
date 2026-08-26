from enum import StrEnum


class UserRole(StrEnum):
    """Sistem genelinde RBAC için kullanılan kullanıcı rol türleri.

    Kiracılık hiyerarşisinin her seviyesi için bir tane olmak üzere dört rol:

    - ROOT: herhangi bir şirkete bağlı olmayan platform operatörü
      (``UserModel.company_id`` yalnızca bu rol için NULL'dur). Her
      şirketi görür, asla bir şirketin iş verisini doğrudan görmez -- bir
      root öznesinin herhangi bir şirket-kaynağı eylemine izin verilmeden
      önce açıkça bir şirkete nasıl kapsanması gerektiği için
      ``app.core.authz``'ye bakın.
    - ADMIN: root tarafından oluşturulan, tam olarak bir şirkete kapsanan
      bir şirket admini.
    - MANAGER: o şirketin admini tarafından atanan bir şirket müdürü.
    - EMPLOYEE: bir admin veya müdür tarafından atanan bir şirket çalışanı.

    ROOT, ADMIN ve MANAGER'ın hepsi her gizlilik seviyesini açar (bkz.
    ``GuardrailPolicy.role_clearance_map``) -- MANAGER, ADMIN ile aynı tam
    erişime güvenilen bir şirket müdürünü temsil eder. EMPLOYEE'nin tavanı
    rol tarafından hiç sabitlenmemiştir: o bireyin kendi
    ``UserModel.clearance_level``'ından gelir, çünkü iki çalışan meşru
    biçimde farklı erişime ihtiyaç duyabilir.
    """

    ROOT = "root"
    ADMIN = "admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"
