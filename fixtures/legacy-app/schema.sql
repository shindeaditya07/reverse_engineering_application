CREATE TABLE customers (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(200) NOT NULL,
  credit DECIMAL(10,2) NOT NULL DEFAULT 0
);

CREATE TABLE users (
  id INT PRIMARY KEY AUTO_INCREMENT,
  token VARCHAR(64) NOT NULL,
  role ENUM('staff','admin') NOT NULL,
  tier ENUM('basic','gold') NOT NULL DEFAULT 'basic'
);

CREATE TABLE orders (
  id INT PRIMARY KEY AUTO_INCREMENT,
  ref VARCHAR(40) NOT NULL,
  customer_id INT NOT NULL,
  total DECIMAL(10,2) NOT NULL,
  status ENUM('new','paid','shipped','cancelled','refunded') NOT NULL,
  flag_x TINYINT NOT NULL DEFAULT 0,
  delivered_at DATETIME NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE order_items (
  id INT PRIMARY KEY AUTO_INCREMENT,
  order_id INT NOT NULL,
  sku VARCHAR(40) NOT NULL,
  qty INT NOT NULL,
  FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE stock (
  sku VARCHAR(40) PRIMARY KEY,
  on_hand INT NOT NULL
);

CREATE TABLE shipments (
  id INT PRIMARY KEY AUTO_INCREMENT,
  order_id INT NOT NULL,
  carrier VARCHAR(40),
  shipped_at DATETIME
);

DELIMITER //
CREATE TRIGGER trg_order_item_stock BEFORE INSERT ON order_items
FOR EACH ROW
BEGIN
  DECLARE have INT;
  SELECT on_hand INTO have FROM stock WHERE sku = NEW.sku;
  IF have < NEW.qty THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'insufficient stock';
  END IF;
  UPDATE stock SET on_hand = on_hand - NEW.qty WHERE sku = NEW.sku;
END//

CREATE PROCEDURE sp_apply_credit(IN cid INT, IN amt DECIMAL(10,2))
BEGIN
  UPDATE customers SET credit = credit + amt * 0.02 WHERE id = cid;
END//
DELIMITER ;
