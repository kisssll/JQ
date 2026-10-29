-- Решение 0017, п. 2: есть ли в базе заметки и строки лояльности на людей,
-- которые не клиенты салона. Клиент салона — завершённая запись (COMPLETED)
-- у любого мастера этого салона; то же правило, что во вкладке «Клиенты»
-- (app/services/salon_clients.py). Только чтение. Выполняет основная сессия.
--
-- any_booking_here = есть хоть какая-то запись в этом салоне (ожидающая,
-- отменённая): такой человек по новому правилу тоже не клиент, но это не
-- посторонний, а «ещё не пришёл» — разбирать отдельно от остальных.

-- 1. Заметки
SELECT n.salon_id, n.client_id,
       count(*)                              AS notes,
       min(n.created_at)                     AS first_note,
       max(n.created_at)                     AS last_note,
       EXISTS (SELECT 1 FROM bookings b JOIN masters m ON m.id = b.master_id
                WHERE m.salon_id = n.salon_id AND b.client_id = n.client_id) AS any_booking_here
  FROM client_notes n
 WHERE NOT EXISTS (SELECT 1 FROM bookings b JOIN masters m ON m.id = b.master_id
                    WHERE m.salon_id = n.salon_id AND b.client_id = n.client_id
                      AND b.status = 'COMPLETED')
 GROUP BY n.salon_id, n.client_id
 ORDER BY n.salon_id, n.client_id;

-- 2. Строки лояльности (с тем, что в них записано, и движениями баллов)
SELECT cl.salon_id, cl.client_id, cl.is_regular_client, cl.personal_discount_percent,
       cl.bonus_points,
       (SELECT count(*) FROM loyalty_points_movements mv WHERE mv.client_loyalty_id = cl.id) AS movements,
       EXISTS (SELECT 1 FROM bookings b JOIN masters m ON m.id = b.master_id
                WHERE m.salon_id = cl.salon_id AND b.client_id = cl.client_id) AS any_booking_here
  FROM client_loyalty cl
 WHERE NOT EXISTS (SELECT 1 FROM bookings b JOIN masters m ON m.id = b.master_id
                    WHERE m.salon_id = cl.salon_id AND b.client_id = cl.client_id
                      AND b.status = 'COMPLETED')
 ORDER BY cl.salon_id, cl.client_id;
