// Tenant registration and directory (split from ui.js)

window.openTenantRegistrationModal = function () {
  const modal = document.getElementById('tenant-registration-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  const err = document.getElementById('tenant-registration-error');
  if (err) {
    err.classList.add('hidden');
    err.textContent = '';
  }
};

window.closeTenantRegistrationModal = function () {
  const modal = document.getElementById('tenant-registration-modal');
  if (!modal) return;
  modal.classList.add('hidden');
  const form = {
    tenantName: document.getElementById('tenant-name'),
    adminUsername: document.getElementById('tenant-admin-username'),
    adminPassword: document.getElementById('tenant-admin-password'),
    coreProjectPath: document.getElementById('tenant-core-project-path')
  };
  Object.values(form).forEach((field) => {
    if (field) field.value = '';
  });
};

window.submitTenantRegistration = async function () {
  const currentUser = window.AppState && window.AppState.currentUser ? window.AppState.currentUser : null;
  const currentRole = String((currentUser && currentUser.role) || '').trim().replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').toLowerCase();
  if (currentRole !== 'platform_admin' && currentRole !== 'admin') {
    const err = document.getElementById('tenant-registration-error');
    if (err) {
      err.textContent = 'ACCESS DENIED: ONLY PLATFORM ADMINS CAN REGISTER TENANTS.';
      err.classList.remove('hidden');
    }
    return;
  }

  const tenantName = document.getElementById('tenant-name')?.value?.trim() || '';
  const adminUsername = document.getElementById('tenant-admin-username')?.value?.trim() || '';
  const adminPassword = document.getElementById('tenant-admin-password')?.value || '';
  const coreProjectPath = document.getElementById('tenant-core-project-path')?.value?.trim() || '';
  const err = document.getElementById('tenant-registration-error');

  if (!tenantName || !adminUsername || !adminPassword) {
    if (err) {
      err.textContent = 'TENANT NAME, ADMIN USERNAME, AND PASSWORD ARE REQUIRED.';
      err.classList.remove('hidden');
    }
    return;
  }

  try {
    const response = await fetch('/api/tenants/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tenant_name: tenantName,
        admin_username: adminUsername,
        admin_password: adminPassword,
        core_project_path: coreProjectPath,
      }),
    });

    const result = await response.json();
    if (!response.ok || !result.ok) {
      if (err) {
        err.textContent = result.error || 'TENANT REGISTRATION FAILED.';
        err.classList.remove('hidden');
      }
      return;
    }

    if (err) {
      err.textContent = 'TENANT CREATED SUCCESSFULLY.';
      err.classList.remove('hidden');
      err.classList.add('text-emerald-400');
      err.classList.remove('text-red-400');
    }
    window.closeTenantRegistrationModal();
    window.loadTenantDirectory?.();
    window.logToTerminal && window.logToTerminal('TENANTS', `Registered tenant: ${tenantName}`, 'text-emerald-400');
  } catch (error) {
    if (err) {
      err.textContent = 'TENANT REGISTRATION REQUEST FAILED.';
      err.classList.remove('hidden');
    }
  }
};

window.loadTenantDirectory = async function () {
  const currentUser = window.AppState && window.AppState.currentUser ? window.AppState.currentUser : null;
  const currentRole = String((currentUser && currentUser.role) || '').trim().replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').toLowerCase();
  if (currentRole !== 'platform_admin' && currentRole !== 'admin') {
    return;
  }

  const listEl = document.getElementById('tenant-directory-list');
  if (!listEl) return;

  try {
    const { payload, ok } = await window.fetchApi('/api/tenants', { cache: 'no-store' });
    if (!ok) {
      listEl.innerHTML = '<div class="text-red-400 text-[10px] uppercase tracking-widest">Tenant directory unavailable.</div>';
      return;
    }

    const tenants = Array.isArray(payload.tenants) ? payload.tenants : [];
    if (!tenants.length) {
      listEl.innerHTML = '<div class="text-cyan-600 text-[10px] uppercase tracking-widest">No tenants registered.</div>';
      return;
    }

    listEl.innerHTML = tenants.map((tenant) => {
      const id = tenant.id || 'unknown';
      const name = tenant.name || id;
      const userCount = Array.isArray(tenant.users) ? tenant.users.length : tenant.user_count || 0;
      const status = tenant.status || 'active';
      return `
        <div class="border border-cyan-900/50 bg-black/20 p-2 rounded-sm">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-[10px] font-bold text-cyan-300 uppercase tracking-[0.2em]">${name}</div>
              <div class="text-[8px] text-cyan-600 tracking-widest">ID: ${id} · ${userCount} USERS · ${status}</div>
            </div>
            <div class="flex items-center gap-2">
              <button onclick="window.openTenantUsers('${id}')" class="btn-ui btn-ui-cyan px-3 py-1 text-[9px] font-bold tracking-widest">OPEN</button>
              <button onclick="window.deleteTenant('${id}')" class="btn-ui btn-ui-red px-3 py-1 text-[9px] font-bold tracking-widest">DELETE</button>
            </div>
          </div>
        </div>
      `;
    }).join('');
  } catch (error) {
    listEl.innerHTML = '<div class="text-red-400 text-[10px] uppercase tracking-widest">Tenant directory unavailable.</div>';
  }
};

window.deleteTenant = async function (tenantId) {
  if (!tenantId || !window.confirm('Delete this tenant and all tenant users?')) {
    return;
  }

  try {
    const { payload, ok } = await window.fetchApi(`/api/tenants/${tenantId}`, { method: 'DELETE', cache: 'no-store' });
    if (!ok) {
      alert(payload.error || 'Unable to delete tenant.');
      return;
    }
    alert('Tenant deleted successfully.');
    window.loadTenantDirectory?.();
    const listEl = document.getElementById('tenant-user-list');
    if (listEl) listEl.innerHTML = '<div class="text-cyan-600 text-[10px] uppercase tracking-widest">No tenant selected.</div>';
  } catch (error) {
    alert('Unable to delete tenant.');
  }
};

window.deleteTenantUser = async function (tenantId, userId, username) {
  if (!tenantId || !userId || !window.confirm(`Delete tenant user ${username || userId}?`)) {
    return;
  }

  try {
    const { payload, ok } = await window.fetchApi(`/api/tenants/${tenantId}/users/${userId}`, { method: 'DELETE', cache: 'no-store' });
    if (!ok) {
      alert(payload.error || 'Unable to delete tenant user.');
      return;
    }
    alert('Tenant user deleted successfully.');
    window.openTenantUsers?.(tenantId);
  } catch (error) {
    alert('Unable to delete tenant user.');
  }
};

window.openTenantUsers = async function (tenantId) {
  const listEl = document.getElementById('tenant-user-list');
  const heading = document.getElementById('tenant-user-list-heading');
  if (!listEl || !heading) return;

  try {
    const { payload, ok } = await window.fetchApi(`/api/tenants/${tenantId}`, { cache: 'no-store' });
    if (!ok || !payload.tenant) {
      listEl.innerHTML = '<div class="text-red-400 text-[10px] uppercase tracking-widest">Unable to load tenant users.</div>';
      return;
    }

    const tenant = payload.tenant;
    heading.textContent = `${tenant.name || tenant.id || 'Tenant'} users`;
    const users = Array.isArray(tenant.users) ? tenant.users : [];

    if (!users.length) {
      listEl.innerHTML = '<div class="text-cyan-600 text-[10px] uppercase tracking-widest">No tenant users found.</div>';
      return;
    }

    listEl.innerHTML = `
      <div class="overflow-hidden border border-cyan-900/50">
        <table class="w-full text-left text-[9px] text-cyan-300">
          <thead class="bg-cyan-950/50 text-cyan-500 uppercase tracking-widest">
            <tr>
              <th class="p-2">Name</th>
              <th class="p-2">Role</th>
              <th class="p-2">Status</th>
              <th class="p-2">Email</th>
              <th class="p-2 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            ${users.map((user) => {
      const role = String(user.role || 'tenant_user').replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').toLowerCase();
      const displayRole = role === 'tenant_admin' ? 'Tenant User Admin' : role === 'tenant_view_user' ? 'Tenant View User' : role === 'platform_admin' ? 'Platform Admin' : 'Tenant View User';
      const email = user.email || user.username || '—';
      const status = user.status || 'active';
      const userId = user.id || user.username || '';
      const username = user.username || user.id || 'Unknown user';
      return `
                <tr class="border-t border-cyan-900/40">
                  <td class="p-2">${username}</td>
                  <td class="p-2">${displayRole}</td>
                  <td class="p-2">${status}</td>
                  <td class="p-2">${email}</td>
                  <td class="p-2 text-right">
                    <button onclick="window.deleteTenantUser('${tenantId}', '${userId}', '${username.replace(/'/g, "\\'")}')" class="btn-ui btn-ui-red px-2 py-1 text-[8px] font-bold tracking-widest">DELETE</button>
                  </td>
                </tr>
              `;
    }).join('')}
          </tbody>
        </table>
      </div>
    `;
  } catch (error) {
    listEl.innerHTML = '<div class="text-red-400 text-[10px] uppercase tracking-widest">Unable to load tenant users.</div>';
  }
};

