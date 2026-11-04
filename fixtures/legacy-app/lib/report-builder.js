var db = global.db;

// Monthly report: built up over several years, one block per metric.
module.exports = function buildReport(month, cb) {
  var out = {};
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 1 */', [month], function (e1, r1) {
    if (e1) { return cb(e1); }
    out['orders_1'] = r1[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 2 */', [month], function (e2, r2) {
    if (e2) { return cb(e2); }
    out['revenue_2'] = r2[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 3 */', [month], function (e3, r3) {
    if (e3) { return cb(e3); }
    out['tax_3'] = r3[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 4 */', [month], function (e4, r4) {
    if (e4) { return cb(e4); }
    out['shipping_4'] = r4[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 5 */', [month], function (e5, r5) {
    if (e5) { return cb(e5); }
    out['refunds_5'] = r5[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 6 */', [month], function (e6, r6) {
    if (e6) { return cb(e6); }
    out['cancellations_6'] = r6[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 7 */', [month], function (e7, r7) {
    if (e7) { return cb(e7); }
    out['new_customers_7'] = r7[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 8 */', [month], function (e8, r8) {
    if (e8) { return cb(e8); }
    out['repeat_customers_8'] = r8[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 9 */', [month], function (e9, r9) {
    if (e9) { return cb(e9); }
    out['gold_orders_9'] = r9[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 10 */', [month], function (e10, r10) {
    if (e10) { return cb(e10); }
    out['avg_order_10'] = r10[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 11 */', [month], function (e11, r11) {
    if (e11) { return cb(e11); }
    out['orders_11'] = r11[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 12 */', [month], function (e12, r12) {
    if (e12) { return cb(e12); }
    out['revenue_12'] = r12[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 13 */', [month], function (e13, r13) {
    if (e13) { return cb(e13); }
    out['tax_13'] = r13[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 14 */', [month], function (e14, r14) {
    if (e14) { return cb(e14); }
    out['shipping_14'] = r14[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 15 */', [month], function (e15, r15) {
    if (e15) { return cb(e15); }
    out['refunds_15'] = r15[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 16 */', [month], function (e16, r16) {
    if (e16) { return cb(e16); }
    out['cancellations_16'] = r16[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 17 */', [month], function (e17, r17) {
    if (e17) { return cb(e17); }
    out['new_customers_17'] = r17[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 18 */', [month], function (e18, r18) {
    if (e18) { return cb(e18); }
    out['repeat_customers_18'] = r18[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 19 */', [month], function (e19, r19) {
    if (e19) { return cb(e19); }
    out['gold_orders_19'] = r19[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 20 */', [month], function (e20, r20) {
    if (e20) { return cb(e20); }
    out['avg_order_20'] = r20[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 21 */', [month], function (e21, r21) {
    if (e21) { return cb(e21); }
    out['orders_21'] = r21[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 22 */', [month], function (e22, r22) {
    if (e22) { return cb(e22); }
    out['revenue_22'] = r22[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 23 */', [month], function (e23, r23) {
    if (e23) { return cb(e23); }
    out['tax_23'] = r23[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 24 */', [month], function (e24, r24) {
    if (e24) { return cb(e24); }
    out['shipping_24'] = r24[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 25 */', [month], function (e25, r25) {
    if (e25) { return cb(e25); }
    out['refunds_25'] = r25[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 26 */', [month], function (e26, r26) {
    if (e26) { return cb(e26); }
    out['cancellations_26'] = r26[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 27 */', [month], function (e27, r27) {
    if (e27) { return cb(e27); }
    out['new_customers_27'] = r27[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 28 */', [month], function (e28, r28) {
    if (e28) { return cb(e28); }
    out['repeat_customers_28'] = r28[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 29 */', [month], function (e29, r29) {
    if (e29) { return cb(e29); }
    out['gold_orders_29'] = r29[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 30 */', [month], function (e30, r30) {
    if (e30) { return cb(e30); }
    out['avg_order_30'] = r30[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 31 */', [month], function (e31, r31) {
    if (e31) { return cb(e31); }
    out['orders_31'] = r31[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 32 */', [month], function (e32, r32) {
    if (e32) { return cb(e32); }
    out['revenue_32'] = r32[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 33 */', [month], function (e33, r33) {
    if (e33) { return cb(e33); }
    out['tax_33'] = r33[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 34 */', [month], function (e34, r34) {
    if (e34) { return cb(e34); }
    out['shipping_34'] = r34[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 35 */', [month], function (e35, r35) {
    if (e35) { return cb(e35); }
    out['refunds_35'] = r35[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 36 */', [month], function (e36, r36) {
    if (e36) { return cb(e36); }
    out['cancellations_36'] = r36[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 37 */', [month], function (e37, r37) {
    if (e37) { return cb(e37); }
    out['new_customers_37'] = r37[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 38 */', [month], function (e38, r38) {
    if (e38) { return cb(e38); }
    out['repeat_customers_38'] = r38[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 39 */', [month], function (e39, r39) {
    if (e39) { return cb(e39); }
    out['gold_orders_39'] = r39[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 40 */', [month], function (e40, r40) {
    if (e40) { return cb(e40); }
    out['avg_order_40'] = r40[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 41 */', [month], function (e41, r41) {
    if (e41) { return cb(e41); }
    out['orders_41'] = r41[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 42 */', [month], function (e42, r42) {
    if (e42) { return cb(e42); }
    out['revenue_42'] = r42[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 43 */', [month], function (e43, r43) {
    if (e43) { return cb(e43); }
    out['tax_43'] = r43[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 44 */', [month], function (e44, r44) {
    if (e44) { return cb(e44); }
    out['shipping_44'] = r44[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 45 */', [month], function (e45, r45) {
    if (e45) { return cb(e45); }
    out['refunds_45'] = r45[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 46 */', [month], function (e46, r46) {
    if (e46) { return cb(e46); }
    out['cancellations_46'] = r46[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 47 */', [month], function (e47, r47) {
    if (e47) { return cb(e47); }
    out['new_customers_47'] = r47[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 48 */', [month], function (e48, r48) {
    if (e48) { return cb(e48); }
    out['repeat_customers_48'] = r48[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 49 */', [month], function (e49, r49) {
    if (e49) { return cb(e49); }
    out['gold_orders_49'] = r49[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 50 */', [month], function (e50, r50) {
    if (e50) { return cb(e50); }
    out['avg_order_50'] = r50[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 51 */', [month], function (e51, r51) {
    if (e51) { return cb(e51); }
    out['orders_51'] = r51[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 52 */', [month], function (e52, r52) {
    if (e52) { return cb(e52); }
    out['revenue_52'] = r52[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 53 */', [month], function (e53, r53) {
    if (e53) { return cb(e53); }
    out['tax_53'] = r53[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 54 */', [month], function (e54, r54) {
    if (e54) { return cb(e54); }
    out['shipping_54'] = r54[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 55 */', [month], function (e55, r55) {
    if (e55) { return cb(e55); }
    out['refunds_55'] = r55[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 56 */', [month], function (e56, r56) {
    if (e56) { return cb(e56); }
    out['cancellations_56'] = r56[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 57 */', [month], function (e57, r57) {
    if (e57) { return cb(e57); }
    out['new_customers_57'] = r57[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 58 */', [month], function (e58, r58) {
    if (e58) { return cb(e58); }
    out['repeat_customers_58'] = r58[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 59 */', [month], function (e59, r59) {
    if (e59) { return cb(e59); }
    out['gold_orders_59'] = r59[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 60 */', [month], function (e60, r60) {
    if (e60) { return cb(e60); }
    out['avg_order_60'] = r60[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 61 */', [month], function (e61, r61) {
    if (e61) { return cb(e61); }
    out['orders_61'] = r61[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 62 */', [month], function (e62, r62) {
    if (e62) { return cb(e62); }
    out['revenue_62'] = r62[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 63 */', [month], function (e63, r63) {
    if (e63) { return cb(e63); }
    out['tax_63'] = r63[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 64 */', [month], function (e64, r64) {
    if (e64) { return cb(e64); }
    out['shipping_64'] = r64[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 65 */', [month], function (e65, r65) {
    if (e65) { return cb(e65); }
    out['refunds_65'] = r65[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 66 */', [month], function (e66, r66) {
    if (e66) { return cb(e66); }
    out['cancellations_66'] = r66[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 67 */', [month], function (e67, r67) {
    if (e67) { return cb(e67); }
    out['new_customers_67'] = r67[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 68 */', [month], function (e68, r68) {
    if (e68) { return cb(e68); }
    out['repeat_customers_68'] = r68[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 69 */', [month], function (e69, r69) {
    if (e69) { return cb(e69); }
    out['gold_orders_69'] = r69[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 70 */', [month], function (e70, r70) {
    if (e70) { return cb(e70); }
    out['avg_order_70'] = r70[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 71 */', [month], function (e71, r71) {
    if (e71) { return cb(e71); }
    out['orders_71'] = r71[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 72 */', [month], function (e72, r72) {
    if (e72) { return cb(e72); }
    out['revenue_72'] = r72[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 73 */', [month], function (e73, r73) {
    if (e73) { return cb(e73); }
    out['tax_73'] = r73[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 74 */', [month], function (e74, r74) {
    if (e74) { return cb(e74); }
    out['shipping_74'] = r74[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 75 */', [month], function (e75, r75) {
    if (e75) { return cb(e75); }
    out['refunds_75'] = r75[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 76 */', [month], function (e76, r76) {
    if (e76) { return cb(e76); }
    out['cancellations_76'] = r76[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 77 */', [month], function (e77, r77) {
    if (e77) { return cb(e77); }
    out['new_customers_77'] = r77[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 78 */', [month], function (e78, r78) {
    if (e78) { return cb(e78); }
    out['repeat_customers_78'] = r78[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 79 */', [month], function (e79, r79) {
    if (e79) { return cb(e79); }
    out['gold_orders_79'] = r79[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 80 */', [month], function (e80, r80) {
    if (e80) { return cb(e80); }
    out['avg_order_80'] = r80[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 81 */', [month], function (e81, r81) {
    if (e81) { return cb(e81); }
    out['orders_81'] = r81[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 82 */', [month], function (e82, r82) {
    if (e82) { return cb(e82); }
    out['revenue_82'] = r82[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 83 */', [month], function (e83, r83) {
    if (e83) { return cb(e83); }
    out['tax_83'] = r83[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 84 */', [month], function (e84, r84) {
    if (e84) { return cb(e84); }
    out['shipping_84'] = r84[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 85 */', [month], function (e85, r85) {
    if (e85) { return cb(e85); }
    out['refunds_85'] = r85[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 86 */', [month], function (e86, r86) {
    if (e86) { return cb(e86); }
    out['cancellations_86'] = r86[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 87 */', [month], function (e87, r87) {
    if (e87) { return cb(e87); }
    out['new_customers_87'] = r87[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 88 */', [month], function (e88, r88) {
    if (e88) { return cb(e88); }
    out['repeat_customers_88'] = r88[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 89 */', [month], function (e89, r89) {
    if (e89) { return cb(e89); }
    out['gold_orders_89'] = r89[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 90 */', [month], function (e90, r90) {
    if (e90) { return cb(e90); }
    out['avg_order_90'] = r90[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 91 */', [month], function (e91, r91) {
    if (e91) { return cb(e91); }
    out['orders_91'] = r91[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 92 */', [month], function (e92, r92) {
    if (e92) { return cb(e92); }
    out['revenue_92'] = r92[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 93 */', [month], function (e93, r93) {
    if (e93) { return cb(e93); }
    out['tax_93'] = r93[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 94 */', [month], function (e94, r94) {
    if (e94) { return cb(e94); }
    out['shipping_94'] = r94[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 95 */', [month], function (e95, r95) {
    if (e95) { return cb(e95); }
    out['refunds_95'] = r95[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 96 */', [month], function (e96, r96) {
    if (e96) { return cb(e96); }
    out['cancellations_96'] = r96[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 97 */', [month], function (e97, r97) {
    if (e97) { return cb(e97); }
    out['new_customers_97'] = r97[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 98 */', [month], function (e98, r98) {
    if (e98) { return cb(e98); }
    out['repeat_customers_98'] = r98[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 99 */', [month], function (e99, r99) {
    if (e99) { return cb(e99); }
    out['gold_orders_99'] = r99[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 100 */', [month], function (e100, r100) {
    if (e100) { return cb(e100); }
    out['avg_order_100'] = r100[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 101 */', [month], function (e101, r101) {
    if (e101) { return cb(e101); }
    out['orders_101'] = r101[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 102 */', [month], function (e102, r102) {
    if (e102) { return cb(e102); }
    out['revenue_102'] = r102[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 103 */', [month], function (e103, r103) {
    if (e103) { return cb(e103); }
    out['tax_103'] = r103[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 104 */', [month], function (e104, r104) {
    if (e104) { return cb(e104); }
    out['shipping_104'] = r104[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 105 */', [month], function (e105, r105) {
    if (e105) { return cb(e105); }
    out['refunds_105'] = r105[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 106 */', [month], function (e106, r106) {
    if (e106) { return cb(e106); }
    out['cancellations_106'] = r106[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 107 */', [month], function (e107, r107) {
    if (e107) { return cb(e107); }
    out['new_customers_107'] = r107[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 108 */', [month], function (e108, r108) {
    if (e108) { return cb(e108); }
    out['repeat_customers_108'] = r108[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 109 */', [month], function (e109, r109) {
    if (e109) { return cb(e109); }
    out['gold_orders_109'] = r109[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 110 */', [month], function (e110, r110) {
    if (e110) { return cb(e110); }
    out['avg_order_110'] = r110[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 111 */', [month], function (e111, r111) {
    if (e111) { return cb(e111); }
    out['orders_111'] = r111[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 112 */', [month], function (e112, r112) {
    if (e112) { return cb(e112); }
    out['revenue_112'] = r112[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 113 */', [month], function (e113, r113) {
    if (e113) { return cb(e113); }
    out['tax_113'] = r113[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 114 */', [month], function (e114, r114) {
    if (e114) { return cb(e114); }
    out['shipping_114'] = r114[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 115 */', [month], function (e115, r115) {
    if (e115) { return cb(e115); }
    out['refunds_115'] = r115[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 116 */', [month], function (e116, r116) {
    if (e116) { return cb(e116); }
    out['cancellations_116'] = r116[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 117 */', [month], function (e117, r117) {
    if (e117) { return cb(e117); }
    out['new_customers_117'] = r117[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 118 */', [month], function (e118, r118) {
    if (e118) { return cb(e118); }
    out['repeat_customers_118'] = r118[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 119 */', [month], function (e119, r119) {
    if (e119) { return cb(e119); }
    out['gold_orders_119'] = r119[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 120 */', [month], function (e120, r120) {
    if (e120) { return cb(e120); }
    out['avg_order_120'] = r120[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 121 */', [month], function (e121, r121) {
    if (e121) { return cb(e121); }
    out['orders_121'] = r121[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 122 */', [month], function (e122, r122) {
    if (e122) { return cb(e122); }
    out['revenue_122'] = r122[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 123 */', [month], function (e123, r123) {
    if (e123) { return cb(e123); }
    out['tax_123'] = r123[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 124 */', [month], function (e124, r124) {
    if (e124) { return cb(e124); }
    out['shipping_124'] = r124[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 125 */', [month], function (e125, r125) {
    if (e125) { return cb(e125); }
    out['refunds_125'] = r125[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 126 */', [month], function (e126, r126) {
    if (e126) { return cb(e126); }
    out['cancellations_126'] = r126[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 127 */', [month], function (e127, r127) {
    if (e127) { return cb(e127); }
    out['new_customers_127'] = r127[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 128 */', [month], function (e128, r128) {
    if (e128) { return cb(e128); }
    out['repeat_customers_128'] = r128[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 129 */', [month], function (e129, r129) {
    if (e129) { return cb(e129); }
    out['gold_orders_129'] = r129[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 130 */', [month], function (e130, r130) {
    if (e130) { return cb(e130); }
    out['avg_order_130'] = r130[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 131 */', [month], function (e131, r131) {
    if (e131) { return cb(e131); }
    out['orders_131'] = r131[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 132 */', [month], function (e132, r132) {
    if (e132) { return cb(e132); }
    out['revenue_132'] = r132[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 133 */', [month], function (e133, r133) {
    if (e133) { return cb(e133); }
    out['tax_133'] = r133[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 134 */', [month], function (e134, r134) {
    if (e134) { return cb(e134); }
    out['shipping_134'] = r134[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 135 */', [month], function (e135, r135) {
    if (e135) { return cb(e135); }
    out['refunds_135'] = r135[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 136 */', [month], function (e136, r136) {
    if (e136) { return cb(e136); }
    out['cancellations_136'] = r136[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 137 */', [month], function (e137, r137) {
    if (e137) { return cb(e137); }
    out['new_customers_137'] = r137[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 138 */', [month], function (e138, r138) {
    if (e138) { return cb(e138); }
    out['repeat_customers_138'] = r138[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 139 */', [month], function (e139, r139) {
    if (e139) { return cb(e139); }
    out['gold_orders_139'] = r139[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 140 */', [month], function (e140, r140) {
    if (e140) { return cb(e140); }
    out['avg_order_140'] = r140[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 141 */', [month], function (e141, r141) {
    if (e141) { return cb(e141); }
    out['orders_141'] = r141[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 142 */', [month], function (e142, r142) {
    if (e142) { return cb(e142); }
    out['revenue_142'] = r142[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 143 */', [month], function (e143, r143) {
    if (e143) { return cb(e143); }
    out['tax_143'] = r143[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 144 */', [month], function (e144, r144) {
    if (e144) { return cb(e144); }
    out['shipping_144'] = r144[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 145 */', [month], function (e145, r145) {
    if (e145) { return cb(e145); }
    out['refunds_145'] = r145[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 146 */', [month], function (e146, r146) {
    if (e146) { return cb(e146); }
    out['cancellations_146'] = r146[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 147 */', [month], function (e147, r147) {
    if (e147) { return cb(e147); }
    out['new_customers_147'] = r147[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 148 */', [month], function (e148, r148) {
    if (e148) { return cb(e148); }
    out['repeat_customers_148'] = r148[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 149 */', [month], function (e149, r149) {
    if (e149) { return cb(e149); }
    out['gold_orders_149'] = r149[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 150 */', [month], function (e150, r150) {
    if (e150) { return cb(e150); }
    out['avg_order_150'] = r150[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 151 */', [month], function (e151, r151) {
    if (e151) { return cb(e151); }
    out['orders_151'] = r151[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 152 */', [month], function (e152, r152) {
    if (e152) { return cb(e152); }
    out['revenue_152'] = r152[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 153 */', [month], function (e153, r153) {
    if (e153) { return cb(e153); }
    out['tax_153'] = r153[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 154 */', [month], function (e154, r154) {
    if (e154) { return cb(e154); }
    out['shipping_154'] = r154[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 155 */', [month], function (e155, r155) {
    if (e155) { return cb(e155); }
    out['refunds_155'] = r155[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 156 */', [month], function (e156, r156) {
    if (e156) { return cb(e156); }
    out['cancellations_156'] = r156[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 157 */', [month], function (e157, r157) {
    if (e157) { return cb(e157); }
    out['new_customers_157'] = r157[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* repeat_customers 158 */', [month], function (e158, r158) {
    if (e158) { return cb(e158); }
    out['repeat_customers_158'] = r158[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* gold_orders 159 */', [month], function (e159, r159) {
    if (e159) { return cb(e159); }
    out['gold_orders_159'] = r159[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* avg_order 160 */', [month], function (e160, r160) {
    if (e160) { return cb(e160); }
    out['avg_order_160'] = r160[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* orders 161 */', [month], function (e161, r161) {
    if (e161) { return cb(e161); }
    out['orders_161'] = r161[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* revenue 162 */', [month], function (e162, r162) {
    if (e162) { return cb(e162); }
    out['revenue_162'] = r162[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* tax 163 */', [month], function (e163, r163) {
    if (e163) { return cb(e163); }
    out['tax_163'] = r163[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* shipping 164 */', [month], function (e164, r164) {
    if (e164) { return cb(e164); }
    out['shipping_164'] = r164[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* refunds 165 */', [month], function (e165, r165) {
    if (e165) { return cb(e165); }
    out['refunds_165'] = r165[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* cancellations 166 */', [month], function (e166, r166) {
    if (e166) { return cb(e166); }
    out['cancellations_166'] = r166[0].v;
  db.query('SELECT COUNT(*) AS v FROM orders WHERE MONTH(created_at) = ? /* new_customers 167 */', [month], function (e167, r167) {
    if (e167) { return cb(e167); }
    out['new_customers_167'] = r167[0].v;
    cb(null, out);
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
  });
};
