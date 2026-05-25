/**
 * Módulo de Administración - Argos2
 * Maneja la gestión de usuarios para administradores
 *
 * Nota: Este módulo depende de auth2.js que debe cargarse primero.
 * Las siguientes variables/funciones están definidas en auth2.js:
 * - API_URL
 * - getSession(), clearSession(), isLoggedIn(), isAdmin()
 * - getAccessToken()
 *
 * MOCK_USERS está definido localmente en este archivo como fallback.
 */

// URL base para endpoints de administración
const ADMIN_API_URL = '/api/admin';

// ============================================
// Datos Mock (Fallback cuando el backend no está disponible)
// ============================================
const MOCK_USERS = [
    {
        id: 1,
        username: 'admin',
        email: 'admin@argos2.com',
        nombre_completo: 'Administrador del Sistema',
        rol: 'admin',
        activo: true,
        email_verificado: true,
        fecha_registro: '2026-01-01'
    },
    {
        id: 2,
        username: 'usuario1',
        email: 'usuario1@ejemplo.com',
        nombre_completo: 'Usuario de Prueba',
        rol: 'usuario',
        activo: true,
        email_verificado: true,
        fecha_registro: '2026-03-15'
    },
    {
        id: 3,
        username: 'usuario2',
        email: 'usuario2@ejemplo.com',
        nombre_completo: 'Segundo Usuario',
        rol: 'usuario',
        activo: false,
        email_verificado: false,
        fecha_registro: '2026-04-20'
    }
];

// ============================================
// Funciones de Gestión de Usuarios
// ============================================

/**
 * Obtiene la lista de todos los usuarios
 * @returns {Promise<Array>} Lista de usuarios
 */
async function fetchUsers() {
    try {
        const response = await authenticatedFetch(`${ADMIN_API_URL}/users`, {
            method: 'GET'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al obtener usuarios');
        }

        return await response.json();
    } catch (error) {
        console.warn('Backend no disponible, usando mock:', error.message);
        return mockFetchUsers();
    }
}

/**
 * Cambia el rol de un usuario
 * @param {number} userId - ID del usuario
 * @param {string} newRole - Nuevo rol ('admin' o 'usuario')
 * @returns {Promise<object>} Resultado de la operación
 */
async function changeUserRole(userId, newRole) {
    try {
        const response = await authenticatedFetch(`${ADMIN_API_URL}/users/${userId}/role`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ rol: newRole })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al cambiar rol');
        }

        return await response.json();
    } catch (error) {
        console.warn('Backend no disponible, usando mock:', error.message);
        return mockChangeUserRole(userId, newRole);
    }
}

/**
 * Activa o desactiva un usuario
 * @param {number} userId - ID del usuario
 * @param {boolean} active - Estado activo (true) o inactivo (false)
 * @returns {Promise<object>} Resultado de la operación
 */
async function toggleUserStatus(userId, active) {
    try {
        const response = await authenticatedFetch(`${ADMIN_API_URL}/users/${userId}/status`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ activo: active })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al cambiar estado');
        }

        return await response.json();
    } catch (error) {
        console.warn('Backend no disponible, usando mock:', error.message);
        return mockToggleUserStatus(userId, active);
    }
}

/**
 * Elimina un usuario
 * @param {number} userId - ID del usuario
 * @returns {Promise<object>} Resultado de la operación
 */
async function deleteUser(userId) {
    try {
        const response = await authenticatedFetch(`${ADMIN_API_URL}/users/${userId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error al eliminar usuario');
        }

        return await response.json();
    } catch (error) {
        console.warn('Backend no disponible, usando mock:', error.message);
        return mockDeleteUser(userId);
    }
}

// ============================================
// Funciones Mock (Fallback)
// ============================================

function mockFetchUsers() {
    return new Promise((resolve) => {
        setTimeout(() => {
            resolve([...MOCK_USERS]);
        }, 500);
    });
}

function mockChangeUserRole(userId, newRole) {
    return new Promise((resolve, reject) => {
        setTimeout(() => {
            const user = MOCK_USERS.find(u => u.id === userId);
            
            if (!user) {
                reject(new Error('Usuario no encontrado'));
                return;
            }
            
            // No permitir cambiar el rol del propio admin
            const session = getSession();
            if (session && session.username === user.username) {
                reject(new Error('No puedes cambiar tu propio rol'));
                return;
            }
            
            user.rol = newRole;
            resolve({
                message: `Rol de usuario actualizado a ${newRole}`,
                user
            });
        }, 300);
    });
}

function mockToggleUserStatus(userId, active) {
    return new Promise((resolve, reject) => {
        setTimeout(() => {
            const user = MOCK_USERS.find(u => u.id === userId);
            
            if (!user) {
                reject(new Error('Usuario no encontrado'));
                return;
            }
            
            // No permitir desactivar el propio admin
            const session = getSession();
            if (session && session.username === user.username && !active) {
                reject(new Error('No puedes desactivar tu propia cuenta'));
                return;
            }
            
            user.activo = active;
            resolve({
                message: `Usuario ${active ? 'activado' : 'desactivado'} correctamente`,
                user
            });
        }, 300);
    });
}

function mockDeleteUser(userId) {
    return new Promise((resolve, reject) => {
        setTimeout(() => {
            const userIndex = MOCK_USERS.findIndex(u => u.id === userId);
            
            if (userIndex === -1) {
                reject(new Error('Usuario no encontrado'));
                return;
            }
            
            const user = MOCK_USERS[userIndex];
            
            // No permitir eliminar el propio admin
            const session = getSession();
            if (session && session.username === user.username) {
                reject(new Error('No puedes eliminar tu propia cuenta'));
                return;
            }
            
            MOCK_USERS.splice(userIndex, 1);
            resolve({
                message: 'Usuario eliminado correctamente'
            });
        }, 300);
    });
}

// ============================================
// Funciones de Renderizado
// ============================================

/**
 * Renderiza la tabla de usuarios
 * @param {Array} users - Lista de usuarios
 */
function renderUsersTable(users) {
    const tbody = document.getElementById('users-tbody');
    const noUsers = document.getElementById('no-users');
    const loadingUsers = document.getElementById('loading-users');
    const userCount = document.getElementById('user-count');
    
    if (!tbody) return;
    
    // Ocultar loading
    if (loadingUsers) {
        loadingUsers.style.display = 'none';
    }
    
    // Actualizar contador
    if (userCount) {
        userCount.textContent = `Total: ${users.length} usuario${users.length !== 1 ? 's' : ''}`;
    }
    
    // Mostrar mensaje si no hay usuarios
    if (users.length === 0) {
        if (noUsers) {
            noUsers.style.display = 'block';
        }
        tbody.innerHTML = '';
        return;
    }
    
    if (noUsers) {
        noUsers.style.display = 'none';
    }
    
    // Renderizar filas
    tbody.innerHTML = users.map(user => renderUserRow(user)).join('');
    
    // Agregar event listeners a los botones
    users.forEach(user => {
        // Botón cambiar rol
        const btnRole = document.getElementById(`btn-role-${user.id}`);
        if (btnRole) {
            btnRole.addEventListener('click', () => handleChangeRole(user));
        }
        
        // Botón toggle estado
        const btnStatus = document.getElementById(`btn-status-${user.id}`);
        if (btnStatus) {
            btnStatus.addEventListener('click', () => handleToggleStatus(user));
        }
        
        // Botón eliminar
        const btnDelete = document.getElementById(`btn-delete-${user.id}`);
        if (btnDelete) {
            btnDelete.addEventListener('click', () => handleDeleteUser(user));
        }
    });
}

/**
 * Renderiza una fila de usuario
 * @param {object} user - Datos del usuario
 * @returns {string} HTML de la fila
 */
function renderUserRow(user) {
    const session = getSession();
    const isCurrentUser = session && session.username === user.username;
    
    const statusClass = user.activo ? 'active' : 'inactive';
    const statusText = user.activo ? 'Activo' : 'Inactivo';
    const roleBadgeClass = user.rol === 'admin' ? 'role-admin' : 'role-user';
    
    // Formatear fecha de nacimiento
    const fechaNac = user.fecha_nacimiento ? new Date(user.fecha_nacimiento).toLocaleDateString('es-VE') : '-';
    
    // Formatear documento
    const documento = formatDocument(user.tipo_documento, user.numero_documento);
    
    // Botones deshabilitados para el usuario actual
    const disabledAttr = isCurrentUser ? 'disabled' : '';
    const disabledClass = isCurrentUser ? 'disabled' : '';
    
    return `
        <tr data-user-id="${user.id}">
            <td data-label="ID">${user.id}</td>
            <td data-label="Nombre">${user.nombre_completo}</td>
            <td data-label="Usuario">${user.username}</td>
            <td data-label="Email">${user.email}</td>
            <td data-label="Fecha Nac.">${fechaNac}</td>
            <td data-label="Teléfono">${user.telefono || '-'}</td>
            <td data-label="Documento">${documento}</td>
            <td data-label="Rol"><span class="role-badge ${roleBadgeClass}">${user.rol}</span></td>
            <td data-label="Estado"><span class="status-badge ${statusClass}">${statusText}</span></td>
            <td class="actions-cell" data-label="">
                <button id="btn-role-${user.id}" class="btn-action btn-role ${disabledClass}"
                        title="Cambiar rol" ${disabledAttr}>
                    <img src="assets/icons/escudo.svg" alt="Cambiar rol">
                </button>
                <button id="btn-status-${user.id}" class="btn-action btn-status ${disabledClass}"
                        title="${user.activo ? 'Desactivar' : 'Activar'}" ${disabledAttr}>
                    <img src="assets/icons/${user.activo ? 'candado' : 'check'}.svg" alt="${user.activo ? 'Desactivar' : 'Activar'}">
                </button>
                <button id="btn-delete-${user.id}" class="btn-action btn-delete ${disabledClass}"
                        title="Eliminar" ${disabledAttr}>
                    <img src="assets/icons/candado.svg" alt="Eliminar">
                </button>
            </td>
        </tr>
    `;
}

// ============================================
// Manejadores de Eventos
// ============================================

/**
 * Maneja el cambio de rol de un usuario
 * @param {object} user - Datos del usuario
 */
async function handleChangeRole(user) {
    const newRole = user.rol === 'admin' ? 'usuario' : 'admin';
    const message = `¿Estás seguro de cambiar el rol de ${user.nombre_completo} a ${newRole}?`;
    
    if (!confirmAction(message)) {
        return;
    }
    
    try {
        const result = await changeUserRole(user.id, newRole);
        showToast(result.message, 'success');
        await loadUsers();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * Maneja el cambio de estado de un usuario
 * @param {object} user - Datos del usuario
 */
async function handleToggleStatus(user) {
    const newStatus = !user.activo;
    const message = `¿Estás seguro de ${newStatus ? 'activar' : 'desactivar'} a ${user.nombre_completo}?`;
    
    if (!confirmAction(message)) {
        return;
    }
    
    try {
        const result = await toggleUserStatus(user.id, newStatus);
        showToast(result.message, 'success');
        await loadUsers();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * Maneja la eliminación de un usuario
 * @param {object} user - Datos del usuario
 */
async function handleDeleteUser(user) {
    const message = `¿Estás seguro de eliminar a ${user.nombre_completo}? Esta acción no se puede deshacer.`;
    
    if (!confirmAction(message)) {
        return;
    }
    
    try {
        const result = await deleteUser(user.id);
        showToast(result.message, 'success');
        await loadUsers();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

/**
 * Carga la lista de usuarios
 */
async function loadUsers() {
    const loadingUsers = document.getElementById('loading-users');
    
    // Mostrar loading
    if (loadingUsers) {
        loadingUsers.style.display = 'block';
    }
    
    try {
        const users = await fetchUsers();
        renderUsersTable(users);
    } catch (error) {
        showToast(error.message, 'error');
        if (loadingUsers) {
            loadingUsers.style.display = 'none';
        }
    }
}

// ============================================
// Utilidades
// ============================================

/**
 * Muestra un diálogo de confirmación
 * @param {string} message - Mensaje a mostrar
 * @returns {boolean} true si el usuario confirma
 */
function confirmAction(message) {
    return confirm(message);
}

// ============================================
// Inicialización
// ============================================

document.addEventListener('DOMContentLoaded', async () => {
    // Verificar autenticación y rol de admin
    if (!await checkAuth(true)) {
        return;
    }
    
    // Mostrar nombre del admin
    const session = getSession();
    const adminName = document.getElementById('admin-name');
    if (adminName && session) {
        // Los datos pueden estar en session (mock) o session.user (backend)
        const userData = session.user || session;
        adminName.textContent = userData.nombre_completo || userData.username;
    }
    
    // Cargar usuarios
    loadUsers();
    
    // Manejo del botón de actualizar
    const btnRefresh = document.getElementById('btn-refresh');
    if (btnRefresh) {
        btnRefresh.addEventListener('click', () => {
            loadUsers();
        });
    }
    
    // Manejo del botón de cerrar sesión
    const btnLogout = document.getElementById('btn-logout');
    if (btnLogout) {
        btnLogout.addEventListener('click', async (e) => {
            e.preventDefault();
            try {
                await logout();
                showToast('Sesión cerrada correctamente', 'success');
                window.location.href = 'index.html';
            } catch (error) {
                console.error('Error al cerrar sesión:', error);
                showToast('Error al cerrar sesión', 'error');
                // Cerrar sesión localmente de todos modos
                clearSession();
                window.location.href = 'index.html';
            }
        });
    }
});

// ============================================
// Exportar módulo
// ============================================
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        fetchUsers,
        changeUserRole,
        toggleUserStatus,
        deleteUser,
        renderUsersTable,
        renderUserRow,
        loadUsers,
        confirmAction
    };
}
